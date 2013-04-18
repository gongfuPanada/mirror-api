#!/usr/bin/python

# Copyright (C) 2013 Gerwin Sturm, FoldedSoft e.U.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""RequestHandlers for Glass emulator"""

__author__ = 'scarygami@gmail.com (Gerwin Sturm)'

import utils

import httplib2
import json
import random
import string

from apiclient.discovery import build
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError


class GlassHandler(utils.BaseHandler):
    def get(self):
        template = utils.JINJA.get_template("templates/glass.html")
        state = ''.join(random.choice(string.ascii_uppercase + string.digits) for x in xrange(32))
        self.session["state"] = state
        self.response.out.write(template.render(
            {
                "state": state,
                "client_id": utils.CLIENT_ID,
                "discovery_url": utils.discovery_url
            }
        ))


class GlassConnectHandler(utils.BaseHandler):
    def post(self):
        """
            Exchange the one-time authorization code for a token and verify user.

            Return a channel token for push notifications on success
        """

        self.response.content_type = "application/json"

        state = self.request.get("state")
        gplus_id = self.request.get("gplus_id")
        code = self.request.body

        if state != self.session.get("state"):
            self.response.status = 401
            self.response.out.write(utils.createError(401, "Invalid state parameter"))
            return

        try:
            oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
            oauth_flow.redirect_uri = 'postmessage'
            credentials = oauth_flow.step2_exchange(code)
        except FlowExchangeError:
            self.response.status = 401
            self.response.out.write(utils.createError(401, "Failed to upgrade the authorization code."))
            return

        # Check that the access token is valid.
        access_token = credentials.access_token
        url = ("https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s" % access_token)
        h = httplib2.Http()
        result = json.loads(h.request(url, 'GET')[1])

        # If there was an error in the access token info, abort.
        if result.get("error") is not None:
            self.response.status = 500
            self.response.out.write(json.dumps(result.get("error")))
            return

        # Verify that the access token is used for the intended user.
        if result["user_id"] != gplus_id:
            self.response.status = 401
            self.response.out.write(utils.createError(401, "Token's user ID doesn't match given user ID."))
            return

        # Verify that the access token is valid for this app.
        if result['issued_to'] != utils.CLIENT_ID:
            self.response.status = 401
            self.response.out.write(utils.createError(401, "Token's client ID does not match the app's client ID"))
            return

        self.session["gplus_id"] = gplus_id
        storage = StorageByKeyName(User, gplus_id, "credentials")
        stored_credentials = storage.get()
        if stored_credentials is not None:
            self.response.status = 200
            self.response.out.write(utils.createMessage("Current user is already connected."))
            return

        try:
            # Create a new authorized API client.
            http = httplib2.Http()
            http = credentials.authorize(http)
            service = build(
                "mirror", "v1",
                discoveryServiceUrl=utils.discovery_url + "/discovery/v1/apis/{api}/{apiVersion}/rest",
                http=http
            )

            # Register contacts
            body = {}
            body["acceptTypes"] = ["image/*"]
            body["id"] = "instaglass_sepia"
            body["displayName"] = "Sepia"
            body["imageUrls"] = ["https://mirror-api.appspot.com/images/sepia.jpg"]
            result = service.contacts().insert(body=body).execute()
            logging.info(result)

            # Register subscription
            verifyToken = ''.join(random.choice(string.ascii_letters + string.digits) for x in range(32))
            body = {}
            body["collection"] = "timeline"
            body["operation"] = "UPDATE"
            body["userToken"] = gplus_id
            body["verifyToken"] = verifyToken
            body["callbackUrl"] = config.base_url + "/timeline_update"
            result = service.subscriptions().insert(body=body).execute()
            logging.info(result)

            # Send welcome message
            body = {}
            body["text"] = "Welcome to Instaglass!"
            body["attachments"] = [{"contentType": "image/jpeg", "contentUrl": "https://mirror-api.appspot.com/images/sepia.jpg"}]
            result = service.timeline().insert(body=body).execute()
            logging.info(result)
        except AccessTokenRefreshError:
            self.response.status = 500
            self.response.out.write(createError(500, "Failed to refresh access token."))
            return

        # Store the access, refresh token and verify token
        storage.put(credentials)
        user = ndb.Key("User", gplus_id).get()
        user.verifyToken = verifyToken
        user.put()
        self.response.status = 200
        self.response.out.write(createMessage("Successfully connected user."))

GLASS_ROUTES = [
    ("/glass/connect", GlassConnectHandler),
    ("/glass/", GlassHandler)
]
# Privacy

PiPhi Wyze Camera Bridge processes the Wyze account credentials, API credentials, camera
metadata, and live camera media that a homeowner explicitly configures. Credentials remain in
the managed service's memory and are passed to the embedded bridge process; they are not written
to this service's logs, health responses, diagnostics, or persistent files.

The service contacts Wyze to authenticate the account and establish authorized camera sessions.
Camera media is bridged locally to compatible PiPhi camera services. PiPhi does not operate a
cloud relay for this service and does not collect the homeowner's credentials or video.

Removing the service configuration stops the bridge and clears credentials and generated stream
secrets from service memory. Removing the container clears all remaining ephemeral state.

Do not expose the service API or RTSP listener to the public internet. Questions or privacy
reports can be opened privately through the contact in [SECURITY.md](SECURITY.md).

# Privacy and data handling

The runtime connects only to the configured local camera address. It sends the
configured camera-account credentials to that device through `python-kasa` and
keeps the password only in process memory.

PiPhi receives sanitized state and metadata: opaque hashed device identity,
availability, stale status, optional privacy mode, optional signal strength,
model, hardware, and firmware versions. The runtime does not request, proxy, or
store image, audio, stream, snapshot, detection, MAC-address, raw device-ID,
RTSP/ONVIF URL, or raw `sys_info` data.

Logs and public errors use bounded categories rather than provider exception
text. Deconfiguration removes the in-memory credentials and disconnects the
transport. Python process memory cannot provide forensic erasure guarantees;
stopping the runtime releases its remaining in-memory copies.

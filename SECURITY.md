# Security policy

Report suspected vulnerabilities privately to `support@piphi.io`. Do not include Wyze passwords,
API keys, stream URLs, tokens, or camera images in a public issue.

The supported release line is `0.1.x`. The service must remain reachable only from the local PiPhi
runtime boundary; neither its Core-allocated API port nor TCP port 18554 should be forwarded from
the public internet.

# CORE API probe report

Host: `nb-15835` (Windows-11-10.0.26100-SP0)  
Python: 3.12.10  
Generated: 2026-10-08 18:37:48 UTC  
Endpoint: `https://api.core.ac.uk/v3/search/works/?q=transistor&limit=1`

## Key

- variable: `BIOGRAPH_CORE_API_KEY`
- set in this process: **yes**
- length: 32
- sha256 prefix: `0dea98408599` (compare with a machine where it works)
- format problems: none
- proxy variables set: none

## Requests

| request | expected | HTTP | rate limit | remaining | hits | content type | time | message |
|---|---|---|---|---|---|---|---|---|
| no key | 200, limit 10 | 200 | 10 | 10 | 92304 | application/json | 0.92s |  |
| fake key | 401 | 401 | - | - | - | application/json | 0.28s | The API key you provided is not valid. |
| your key | 200, limit 500 | 200 | 500 | 500 | 92304 | application/json | 0.78s |  |
| no slash | 301 | 301 | 500 | 500 | - | text/html | 0.16s | redirect to https://api.core.ac.uk/v3/search/works/?q=transistor&limit=1 |

## Diagnosis

- The key works from this machine. If a tool still fails here, the tool is sending the request differently: check its shell syntax for the variable, the URL's trailing slash, and that the variable reaches its process.

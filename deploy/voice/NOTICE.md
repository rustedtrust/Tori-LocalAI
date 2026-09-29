# Upstream provenance

Tori's original local wrapper uses the public recorder and external-executor
APIs inspected from KoljaB/RealtimeSTT release v1.1.2:
https://github.com/KoljaB/RealtimeSTT/tree/v1.1.2
The accepted PoC records checkout 07df3600286ea7794cf87d905aab6fccbb09dfc0.
No upstream source was patched or vendored wholesale. The reference server's
lifecycle, structured recording IDs, and scheduler/executor arrangement informed
this narrow wrapper. Preserve this notice and the upstream license below when
redistributing the integration; separately prepared dependencies/models retain
all of their own license requirements.

MIT License

Copyright (c) 2023 Kolja Beigel

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

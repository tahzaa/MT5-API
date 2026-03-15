Instructions
1. Download Python, download the standalone installer from https://www.python.org/downloads
2. Download Metatrader 5 from https://www.metatrader5.com/en/download
3. clone project by, git clone https://github.com/tahzaa/MT5-API.git
4. create virtual python env, python -m venv venv
5. on project path, venv\Scripts\activate
6. run, pip install -r requirements.txt
7. open Metatrader 5 on Windows, Login to trading account correctly
8. run, uvicorn app:app --host 0.0.0.0 --port 8000

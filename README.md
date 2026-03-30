Instructions
1. Download Python, download the standalone installer from https://www.python.org/downloads
2. Download Metatrader 5 from https://www.metatrader5.com/en/download
3. Download Git from https://git-scm.com/install
4. clone project by, git clone https://github.com/tahzaa/MT5-API.git
5. create virtual python env, python -m venv venv
6. on project path, venv\Scripts\activate
7. run, pip install -r requirements.txt
8. open Metatrader 5 on Windows, Login to trading account correctly
9. run, uvicorn app:app --host 0.0.0.0 --port 8000

For any PC already proceed steps above
1. venv\Scripts\activate
2. uvicorn app:app --host 0.0.0.0 --port 8000

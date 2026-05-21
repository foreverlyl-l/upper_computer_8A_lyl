@echo off
cd /d E:\interesting\???-??\backend
set ENVIRONMENT=development
set AUTO_SEED_DEFAULT_USERS=false
set SECRET_KEY=this_is_a_local_test_secret_key_which_is_long_enough_123456
set ADMIN_TOTP_SECRET=GUPNCCCEIT72YWGMDFFL5KJYDSA2JUXT
set CORS_ORIGINS=["http://127.0.0.1:5500","http://localhost:5500"]
set ALLOWED_HOSTS=["127.0.0.1","localhost"]
E:\Anaconda3\envs\access_backend\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > E:\interesting\???-??\backend\uvicorn.runtime.log 2>&1

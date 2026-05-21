@echo off
set ENVIRONMENT=development
set AUTO_SEED_DEFAULT_USERS=false
set SECRET_KEY=this_is_a_local_test_secret_key_which_is_long_enough_123456
set ADMIN_TOTP_SECRET=GUPNCCCEIT72YWGMDFFL5KJYDSA2JUXT
E:\Anaconda3\envs\access_backend\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

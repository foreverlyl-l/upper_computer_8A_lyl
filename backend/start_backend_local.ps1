Set-Location -Path $PSScriptRoot
$env:ENVIRONMENT = 'development'
$env:AUTO_SEED_DEFAULT_USERS = 'false'
$env:SECRET_KEY = 'this_is_a_local_test_secret_key_which_is_long_enough_123456'
$env:ADMIN_TOTP_SECRET = 'GUPNCCCEIT72YWGMDFFL5KJYDSA2JUXT'
$env:CORS_ORIGINS = '["http://127.0.0.1:5500","http://localhost:5500"]'
$env:ALLOWED_HOSTS = '["127.0.0.1","localhost"]'
& 'E:\Anaconda3\envs\access_backend\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8000

import argparse
from pathlib import Path
import pyotp

def main() -> None:
    parser = argparse.ArgumentParser(description='Generate admin TOTP secret and QR')
    parser.add_argument('--name', default='Admin', help='Account name shown in authenticator')
    parser.add_argument('--issuer', default='智能门禁系统', help='Issuer name')
    parser.add_argument('--output', default='admin_totp_qr.png', help='QR image output path')
    args = parser.parse_args()
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=args.name, issuer_name=args.issuer)
    print(f'ADMIN_TOTP_SECRET={secret}')
    print('# 3. (可选) 生成绑定二维码的链接，你可以在控制台打印出来并用在线生成器转成二维码，用手机扫码')
    print(f'请将此链接生成二维码并用 Google 身份验证器扫描: {provisioning_uri}')
    try:
        import qrcode
        output_path = Path(args.output).resolve()
        img = qrcode.make(provisioning_uri)
        img.save(output_path)
        print(f'二维码已生成: {output_path}')
    except Exception as exc:
        print(f'二维码图片生成失败（可忽略，使用上方 URI 仍可绑定）: {exc}')
if __name__ == '__main__':
    main()

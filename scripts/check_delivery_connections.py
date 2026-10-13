"""Read-only provider checks; never sends messages or prints credentials."""
import asyncio
import json
import aiosmtplib
import httpx
from app.core.config import get_settings


async def main():
    s = get_settings()
    smtp = aiosmtplib.SMTP(hostname=s.smtp_hostname, port=s.smtp_port,
                          use_tls=s.smtp_use_tls, start_tls=not s.smtp_use_tls,
                          timeout=20)
    try:
        await smtp.connect()
        await smtp.login(s.smtp_username, s.smtp_password)
        print(json.dumps({'email': 'authentication_ok', 'message_sent': False}))
    except Exception as exc:
        print(json.dumps({'email': 'authentication_failed', 'error_type': type(exc).__name__,
                          'smtp_code': getattr(exc, 'code', None), 'message_sent': False}))
    finally:
        if smtp.is_connected:
            await smtp.quit()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f'https://graph.facebook.com/v25.0/{s.whatsapp_phone_number_id}',
                headers={'Authorization': f'Bearer {s.whatsapp_access_token}'},
                params={'fields': 'id'})
            error = response.json().get('error', {})
            print(json.dumps({'whatsapp': 'read_access_ok' if response.is_success else 'read_access_failed',
                              'http_status': response.status_code,
                              'error_code': error.get('code'), 'error_subcode': error.get('error_subcode'),
                              'message_sent': False}))
    except Exception as exc:
        print(json.dumps({'whatsapp': 'connection_failed', 'error_type': type(exc).__name__,
                          'message_sent': False}))


if __name__ == '__main__':
    asyncio.run(main())

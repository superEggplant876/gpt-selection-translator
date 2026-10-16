# Security

Never include the `data/` directory, `.dpapi` files, access tokens, refresh tokens, passwords, or authorization codes in issues, commits, screenshots, or archives.

If a credential is exposed, revoke the app grant using the official account controls and sign in again. Removing a file from the latest commit does not remove it from Git history.

This application stores protected credentials locally and sends explicitly requested translations to OpenAI. It is not an OpenAI product and does not include a shared account or shared usage quota.

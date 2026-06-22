# Google Play Service Account Setup Guide

This guide walks through creating a Google Cloud service account with the permissions AppShip needs to upload Android App Bundles and query release tracks on Google Play Console.

---

## Prerequisites

- A **Google Play Console** account with **Admin** or **Account owner** permissions
- An existing app in Google Play Console (at minimum, the app listing must be created — a draft is fine)
- AppShip installed: `pip install -e /path/to/AppShip`

---

## Step 1: Create a Google Cloud Project

If you already have a Google Cloud project linked to your Play Console, skip to Step 2.

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. In the top navigation bar, click the **project dropdown** (to the right of the "Google Cloud" logo)
3. Click **NEW PROJECT** (top-right of the dialog)
4. Fill in:
   - **Project name** — e.g., `MyApp Play Publishing`
   - **Location** — leave as "No organization" unless you have one
5. Click **CREATE**
6. Wait for the notification "Project created" and click **SELECT PROJECT** to switch to it

> **Note:** It may take 30–60 seconds for the project to fully initialize before APIs can be enabled.

---

## Step 2: Enable the Android Publisher API

1. In your newly created project, navigate to **APIs & Services > Library**
   - From the left sidebar menu, or go to: [https://console.cloud.google.com/apis/library](https://console.cloud.google.com/apis/library)
2. In the search bar, type: `Android Publisher API`
3. Click the **Android Publisher API** result (published by Google)
4. Click **ENABLE**
5. Wait for the confirmation — you should see a green checkmark and the API status change to "API Enabled"

---

## Step 3: Create a Service Account

1. From the left sidebar, go to **IAM & Admin > Service Accounts**
   - Or navigate to: [https://console.cloud.google.com/iam-admin/serviceaccounts](https://console.cloud.google.com/iam-admin/serviceaccounts)
2. Click **+ CREATE SERVICE ACCOUNT** at the top
3. **Step 1 — Service account details:**
   - **Service account name:** e.g., `appship-publisher`
   - **Service account ID:** auto-filled from the name (e.g., `appship-publisher`)
   - **Description:** e.g., `AppShip automated Google Play publishing`
   - Click **CREATE AND CONTINUE**
4. **Step 2 — Grant this service account access to project:**
   - Click the **Role** dropdown
   - Type `Release Manager` in the filter, but note: this exact role may not exist in IAM. Instead:
     - Select **Service Account User** (under "Service Accounts")
     - Click **+ ADD ANOTHER ROLE**
     - Select **Viewer** (under "Basic") — needed for API discovery
   - Click **CONTINUE**
5. **Step 3 — Grant users access:**
   - Skip this for now (the service account email will be invited to Play Console in Step 5)
   - Click **DONE**

> **Why not "Release Manager" here?** The `Release Manager` role is a **Play Console** permission, not a Google Cloud IAM role. The actual Play Console permissions are granted in Step 5. The IAM roles here (`Service Account User` + `Viewer`) are the minimum needed for the service account to authenticate and call the Android Publisher API.

---

## Step 4: Create and Download the JSON Key File

1. On the **Service Accounts** page, find your newly created service account in the list
2. Click its **email address** to open the details page
3. Click the **KEYS** tab near the top
4. Click **ADD KEY > Create new key** (dropdown button)
5. Select **JSON** as the key type
6. Click **CREATE**
7. Your browser will download a `.json` file — save it to a secure location on your machine

   Recommended path (Windows):
   ```
   %USERPROFILE%\.appship\service-account.json
   ```
   Or (macOS / Linux):
   ```
   ~/.appship/service-account.json
   ```

8. **IMPORTANT:** This JSON file contains a private key. Treat it like a password:
   - Never commit it to version control
   - Add `*.json` or the specific filename to your `.gitignore`
   - Restrict file permissions: `chmod 600 service-account.json`

### Key File Contents (for reference)

The downloaded JSON looks like this:
```json
{
  "type": "service_account",
  "project_id": "myapp-play-publishing",
  "private_key_id": "abc123...",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
  "client_email": "appship-publisher@myapp-play-publishing.iam.gserviceaccount.com",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token"
}
```

Note the **`client_email`** field — you will need this email address for the next step.

---

## Step 5: Invite the Service Account to Google Play Console

This is the most commonly missed step. The service account must be explicitly invited as a user in **Google Play Console** with the appropriate permissions.

1. Go to [Google Play Console](https://play.google.com/console/)
2. Select your app (or create a draft app if you haven't already)
3. From the left sidebar, expand **Users and permissions**
4. Click **Invite new users**
5. In the invitation form:
   - **Email address:** Paste the `client_email` from the JSON key file (e.g., `appship-publisher@myapp-play-publishing.iam.gserviceaccount.com`)
   - **Account type:** Leave as "User"
   - **App permissions:** Click **Add app**, select your app
   - **Role / Permission set:** Select **Release manager** from the dropdown
     - This gives the account permission to: upload bundles/APKs, manage testing tracks (internal, alpha, beta), and promote to production
   - Optionally add **Store listing** permissions if AppShip will manage store metadata in the future
6. Click **Invite user**
7. Click **Send invitation** in the confirmation dialog

> **Note:** The invitation is accepted automatically for service accounts — no manual acceptance is needed. However, it can take **up to 2 minutes** for the permission to propagate to Google's API. If you get a 403 error immediately after inviting, wait 2–3 minutes and try again.

### Permission Level Reference

| Role | Can do | Recommended for |
|------|--------|-----------------|
| **Release manager** | Upload, manage tracks, promote to production | ✅ AppShip (minimum) |
| **Admin** | All of the above + manage users, billing, app signing | Overkill for automation |
| **View app information** | Read-only access to tracks and releases | Read-only status checks only |

---

## Step 6: Set the `GOOGLE_PLAY_SERVICE_ACCOUNT` Environment Variable

AppShip reads the service account path from the `GOOGLE_PLAY_SERVICE_ACCOUNT` environment variable.

### Option A: Set per-session (temporary)

**Windows (Command Prompt):**
```cmd
set GOOGLE_PLAY_SERVICE_ACCOUNT=C:\Users\YourName\.appship\service-account.json
```

**Windows (PowerShell):**
```powershell
$env:GOOGLE_PLAY_SERVICE_ACCOUNT = "C:\Users\YourName\.appship\service-account.json"
```

**macOS / Linux (bash/zsh):**
```bash
export GOOGLE_PLAY_SERVICE_ACCOUNT="$HOME/.appship/service-account.json"
```

### Option B: Set permanently

**Windows:**
1. Open **System Properties > Advanced > Environment Variables**
2. Under "User variables", click **New**
3. Variable name: `GOOGLE_PLAY_SERVICE_ACCOUNT`
4. Variable value: `C:\Users\YourName\.appship\service-account.json`
5. Click **OK** and restart your terminal

**macOS / Linux:**
Add to your shell profile (`~/.bashrc`, `~/.zshrc`, or `~/.profile`):
```bash
export GOOGLE_PLAY_SERVICE_ACCOUNT="$HOME/.appship/service-account.json"
```

### Option C: Set in Hermes Agent profile

If using AppShip as a Hermes skill, set the variable in your Hermes profile configuration or shell init so the agent process inherits it.

---

## Step 7: Set the `APPSHIP_KEYSTORE_PASSWORD` Environment Variable (Optional)

If your project uses a keystore for signing and requires a password at build time, set this variable:

```bash
export APPSHIP_KEYSTORE_PASSWORD=your_keystore_password
```

AppShip automatically maps this to Gradle properties:
- `ORG_GRADLE_PROJECT_keyPassword` = value of `APPSHIP_KEYSTORE_PASSWORD`
- `ORG_GRADLE_PROJECT_storePassword` = value of `APPSHIP_KEYSTORE_PASSWORD`

> **Security:** Store the keystore password in a password manager or secrets vault. Never hardcode it in build scripts or commit it to version control.

---

## Step 8: Verify the Setup

Run the AppShip status command to verify everything is configured correctly:

```bash
appship status com.yourcompany.yourapp
```

Replace `com.yourcompany.yourapp` with your actual Android package name (also called Application ID in Play Console).

### What to expect from a successful check

```json
{
  "status": "ok",
  "package_name": "com.yourcompany.yourapp",
  "tracks": [
    {"track": "internal", "version_code": null, "status": "no_releases"},
    {"track": "alpha", "version_code": null, "status": "no_releases"},
    {"track": "beta", "version_code": null, "status": "no_releases"},
    {"track": "production", "version_code": null, "status": "no_releases"}
  ]
}
```

If you see `"status": "ok"` with track data, **your setup is complete**.

If you have existing releases, the `version_code` and `status` fields will show active versions (e.g., `"status": "completed"`, `"status": "draft"`, `"status": "inProgress"`, etc.).

### Also verify the full workflow

```bash
# 1. Analyze your Android project
appship analyze /path/to/your/android/project

# 2. Build the AAB
appship build /path/to/your/android/project

# 3. Check status (no upload yet, just verifying connectivity)
appship status com.yourcompany.yourapp
```

---

## Troubleshooting

### `GOOGLE_PLAY_SERVICE_ACCOUNT env var not set`

**Symptom:**
```json
{
  "status": "failed",
  "error_summary": "GOOGLE_PLAY_SERVICE_ACCOUNT env var not set",
  "suggestion": "Set this to the path of your Google Play service account JSON key file."
}
```

**Fix:**
- Verify the environment variable is set: `echo $GOOGLE_PLAY_SERVICE_ACCOUNT`
- If you set it in a different terminal, it won't carry over — set it in the current session or permanently (see Step 6)
- Check for typos in the variable name: it must be exactly `GOOGLE_PLAY_SERVICE_ACCOUNT`

---

### Service account key file not found

**Symptom:**
```json
{
  "status": "failed",
  "error_summary": "Service account key file not found: /path/to/file.json",
  "suggestion": "Check the GOOGLE_PLAY_SERVICE_ACCOUNT path."
}
```

**Fix:**
- Verify the file exists at the exact path: `ls "$GOOGLE_PLAY_SERVICE_ACCOUNT"`
- On Windows, use forward slashes or escaped backslashes: `C:/Users/Name/.appship/service-account.json`
- Check that the filename is correct — the downloaded file is often named something like `myapp-play-publishing-abc123.json`; you may want to rename it to `service-account.json`

---

### 403 Forbidden / Permission denied

**Symptom:**
```json
{
  "status": "failed",
  "error_summary": "<HttpError 403 ...>",
  "suggestion": "Service account may lack permissions. Ensure it has 'Release manager' role in Play Console."
}
```

This is the most common error. It means the API call was authenticated but the service account lacks the required Play Console permissions.

**Fix checklist (in order):**

1. **Is the service account invited to Play Console?** (Step 5)
   - Go to Play Console > **Users and permissions** > check that the service account email appears in the user list
   - If not, invite it with **Release manager** role

2. **Is the invitation for the correct app?**
   - In Users and permissions, click the service account, then the **App permissions** tab
   - Verify your app is listed and the role is **Release manager** (not "View app information")

3. **Has the permission propagated?**
   - New invitations can take 2–5 minutes to take effect
   - Wait and try again

4. **Is the Android Publisher API enabled?** (Step 2)
   - Go to Google Cloud Console > **APIs & Services > Enabled APIs & services**
   - Verify "Android Publisher API" appears in the list with a green checkmark

5. **Is the service account in the correct Google Cloud project?**
   - Verify the `project_id` in your JSON key file matches the project where the API is enabled
   - You can check: `cat service-account.json | grep project_id`

---

### Package not found

**Symptom:**
```json
{
  "status": "failed",
  "error_summary": "Package not found: com.yourcompany.yourapp",
  "suggestion": "Package name not found. Check that the app exists in Play Console."
}
```

**Fix:**
- Verify the app exists in Google Play Console at [https://play.google.com/console/](https://play.google.com/console/)
- If the app exists: check that your package name matches exactly (case-sensitive)
  - In Play Console, go to your app > **Dashboard** — the package name is shown at the top
  - Package name = Application ID in `build.gradle`
- If the app doesn't exist yet: create a draft app in Play Console first
  - Go to Play Console > **All apps > Create app**
  - Fill in the app name and default language
  - Select "Free" or "Paid"
  - Accept the declarations
  - Click **Create app**
  - It doesn't need a full store listing — a draft is sufficient for API access

---

### Missing Google API client libraries

**Symptom:**
```json
{
  "status": "failed",
  "error_summary": "Missing Google API client libraries",
  "suggestion": "Install: pip install google-auth google-api-python-client"
}
```

**Fix:**
```bash
pip install google-auth google-api-python-client
```

Or ensure the AppShip package is installed with its dependencies:
```bash
pip install -e /path/to/AppShip
```

---

### expired / invalid_grant

**Symptom:**
```
google.auth.exceptions.RefreshError: invalid_grant: ...
```

**Fix:**
- This can happen if the service account key was deleted/rotated in Google Cloud Console
- Create a new JSON key file (Step 4) and update `GOOGLE_PLAY_SERVICE_ACCOUNT` to point to it
- Also check that the system clock is accurate — OAuth2 tokens are time-sensitive

---

### Permission Propagation Delays

If you just invited the service account and are getting 403 errors:

1. Wait **2–5 minutes** after inviting the service account before testing
2. If the error persists after 5 minutes, try removing and re-inviting the service account
3. As a last resort, try granting **Admin** permissions temporarily to verify the API connection works, then downgrade to **Release manager**

---

## Quick Checklist

Before troubleshooting, verify each of these:

- [ ] Google Cloud Project created
- [ ] Android Publisher API enabled in that project
- [ ] Service account created in that project
- [ ] JSON key file downloaded and saved locally
- [ ] Service account email invited to Play Console with **Release manager** role
- [ ] The invitation is for the correct app
- [ ] `GOOGLE_PLAY_SERVICE_ACCOUNT` env var points to the JSON key file
- [ ] `appship status com.yourpackage.name` returns `"status": "ok"`

---

## Security Best Practices

1. **Never commit the JSON key file** to version control. Add it to `.gitignore`:
   ```
   # .gitignore
   *.service-account.json
   service-account.json
   ```

2. **Restrict file permissions:**
   ```bash
   chmod 600 ~/.appship/service-account.json
   ```

3. **Use a dedicated service account** — do not reuse one that has broader permissions

4. **Rotate keys periodically:** In Google Cloud Console, delete old keys and create new ones (this invalidates the old key)

5. **Principle of least privilege:** The service account only needs **Release manager** on the specific app. Do not grant Admin or Owner permissions unless absolutely necessary.

6. **Store the keystore password securely:** Use a secrets manager (e.g., 1Password CLI, AWS Secrets Manager, HashiCorp Vault) instead of plaintext environment variables in production CI/CD environments.

---

## Next Steps

After verifying the setup:

1. **Analyze your project:** `appship analyze /path/to/your/android/project`
2. **Build the AAB:** `appship build /path/to/your/android/project`
3. **Upload to internal track:** `appship upload /path/to/app.aab com.yourpackage.name --track internal`
4. **Check status:** `appship status com.yourpackage.name`

See [SPEC.md](SPEC.md) for the full tool catalog and architecture reference.

# SSO: SAML 2.0 and OIDC Integration

This document outlines the SSO integration for Engram using SAML 2.0 and OIDC.

## Overview

| Protocol | Status | Use Case |
|----------|--------|----------|
| OIDC | Planned | Modern IdPs (Google, Okta, Auth0) |
| SAML 2.0 | Planned | Enterprise IdPs (ADFS, Azure AD) |

## Supported Identity Providers

### OIDC

| Provider | Config Format | Docs |
|----------|---------------|------|
| Google Workspace | Client ID + Secret | [Guide](https://developers.google.com/identity/protocols/oauth2) |
| Okta | Domain + Client ID + Secret | [Guide](https://developer.okta.com/docs/concepts/auth-servers) |
| Auth0 | Domain + Client ID + Secret | [Guide](https://auth0.com/docs) |
| Azure AD | Tenant ID + Client ID + Secret | [Guide](https://docs.microsoft.com/en-us/azure/active-directory/develop) |

### SAML 2.0

| Provider | Metadata URL | Docs |
|----------|------------|------|
| Azure AD | Entity ID | [Guide](https://docs.microsoft.com/en-us/azure/active-directory/develop/saml-configuration) |
| Okta | SAML XML | [Guide](https://developer.okta.com/docs/concepts/saml) |
| ADFS | Federation Metadata | [Guide](https://docs.microsoft.com/en-us/windows-server/identity/ad-fs/deployment) |
| OneLogin | App Metadata | [Guide](https://developers.onelogin.com/saml) |

## Architecture

### OIDC Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        OIDC Authentication                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   User clicks SSO                                                │
│         │                                                       │
│         ▼                                                       │
│   ┌─────────────────┐                                           │
│   │  Redirect to   │                                           │
│   │  IdP (Okta,    │                                           │
│   │  Google, etc)  │                                           │
│   └────────┬────────┘                                           │
│            │                                                    │
│            ▼                                                    │
│   ┌─────────────────┐                                           │
│   │   IdP Login    │                                           │
│   │   (hosted)     │                                           │
│   └────────┬────────┘                                           │
│            │                                                    │
│            ▼                                                    │
│   ┌─────────────────┐                                           │
│   │  Callback with │                                           │
│   │  Authorization │                                           │
│   │  Code          │                                           │
│   └────────┬────────┘                                           │
│            │                                                    │
│            ▼                                                    │
│   ┌─────────────────┐                                           │
│   │  Exchange code  │                                           │
│   │  for tokens    │                                           │
│   └────────┬────────┘                                           │
│            │                                                    │
│            ▼                                                    │
│   ┌─────────────────────────┐                                   │
│   │  Create session with    │                                   │
│   │  user claims           │                                   │
│   └─────────────────────────┘                                   │
└─────────────────────────────────────────────────────────────────┘
```

### SAML Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      SAML 2.0 Authentication                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   User clicks SSO                                                │
│         │                                                       │
│         ▼                                                       │
│   ┌─────────────────────────┐                                       │
│   │ Generate SAML AuthN  │                                       │
│   │ Request            │                                       │
│   └────────┬────────────┘                                       │
│            │                                                    │
│            ▼                                                    │
│   ┌─────────────────────────┐                                       │
│   │  Redirect to IdP with │                                      │
│   │  SAML Request (Base64)  │                                      │
│   └────────┬────────────┘                                       │
│            │                                                    │
│            ▼                                                    │
│   ┌─────────────────────────┐                                       │
│   │  IdP processes      │                                       │
│   │  AuthN Request      │                                       │
│   └────────┬────────────┘                                       │
│            │                                                    │
│            ▼                                                    │
│   ┌─────────────────────────┐                                       │
│   │  IdP posts SAML       │                                       │
│   │  Response (signed)    │                                       │
│   └────────┬────���─��─────┘                                       │
│            │                                                    │
│            ▼                                                    │
│   ┌─────────────────────────┐                                       │
│   │  Validate signature     │                                       │
│   │  Extract claims         │                                       │
│   └────────┬────────────┘                                       │
│            │                                                    │
│            ▼                                                    │
│   ┌─────────────────────────┐                                       │
│   │  Create session with  │                                       │
│   │  user attributes     │                                       │
│   └─────────────────────────┘                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Implementation

### OIDC Configuration

```python
# config/sso.yaml
oidc:
  providers:
    - name: google
      type: oidc
      client_id: "${GOOGLE_CLIENT_ID}"
      client_secret: "${GOOGLE_CLIENT_SECRET}"
      authorization_endpoint: "https://accounts.google.com/o/oauth2/v2/auth"
      token_endpoint: "https://oauth2.googleapis.com/token"
      userinfo_endpoint: "https://www.googleapis.com/oauth2/v3/userinfo"
      scopes:
        - openid
        - email
        - profile

    - name: okta
      type: oidc
      client_id: "${OKTA_CLIENT_ID}"
      client_secret: "${OKTA_CLIENT_SECRET}"
      issuer: "${OKTA_DOMAIN}"
      scopes:
        - openid
        - email
        - profile
```

### SAML Configuration

```python
# config/sso.yaml
saml:
  providers:
    - name: azure_ad
      type: saml
      entity_id: "https://engram.app/sso/saml"
      acs_url: "https://engram.app/sso/saml/acs"
      idp_metadata_url: "https://login.microsoftonline.com/{tenant}/federationmetadata/2007-06/federationmetadata.xml"
      attribute_mappings:
        email: "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"
        name: "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"
```

### Callback Handler

```python
# sso_handler.py
class SSOHandler:
    async def handle_oidc_callback(
        self,
        code: str,
        provider: str,
    ) -> dict:
        """Handle OIDC auth code exchange."""
        config = get_provider_config(provider)
        tokens = await exchange_code_for_tokens(
            code=code,
            client_id=config["client_id"],
            client_secret=config["client_secret"],
            redirect_uri=config["redirect_uri"],
        )
        userinfo = await fetch_userinfo(
            tokens["access_token"],
            config["userinfo_endpoint"],
        )
        return await self.create_session(userinfo)

    async def handle_saml_acs(
        self,
        saml_response: str,
        provider: str,
    ) -> dict:
        """Handle SAML Assertion Consumer Service."""
        config = get_provider_config(provider)
        assertion = await validate_saml_response(
            saml_response,
            idp_cert=config["idp_cert"],
        )
        userinfo = self.map_saml_attributes(assertion)
        return await self.create_session(userinfo)
```

### Attribute Mappings

| SAML Attribute | OIDC Claim | Session Field |
|---------------|-----------|--------------|
| email | email | email |
| firstName | given_name | first_name |
| lastName | family_name | last_name |
| groups | groups | roles |
| userPrincipalName | sub | user_id |

## Security

### Token Validation

```python
# Verify OIDC tokens
async def verify_oidc_token(
    id_token: str,
    provider_config: dict,
) -> dict:
    """Verify and decode OIDC ID token."""
    jwks = await fetch_jwks(provider_config["jwks_uri"])
    claims = decode_jwt(id_token, jwks)
    
    # Verify issuer and audience
    assert claims["iss"] == provider_config["issuer"]
    assert claims["aud"] == provider_config["client_id"]
    
    return claims
```

### SAML Validation

```python
# Verify SAML response
async def validate_saml_response(
    response: str,
    idp_cert: str,
) -> dict:
    """Validate SAML response signature and extract assertions."""
    doc = parse_xml(response)
    
    # Verify signature
    assert verify_xml_signature(doc, idp_cert)
    
    # Extract attributes
    attributes = extract_saml_attributes(doc)
    
    # Check conditions (NotBefore, NotOnOrAfter)
    check_conditions(doc)
    
    return attributes
```

## Configuration UI

### Workspace Admin Settings

```
┌──────────────────────────────────────────────────┐
│ SSO Configuration                                │
├──────────────────────────────────────────────────┤
│                                                  │
│ Provider Type: [OIDC ▼]                           │
│                                                  │
│ Provider: [Google ▼]                             │
│                                                  │
│ Client ID: [____________]                         │
│ Client Secret: [____________]                   │
│                                                  │
│ [Test Connection]                               │
│                                                  │
│ [Save SSO Settings]                            │
└──────────────────────────────────────────────────┘
```

### Environment Variables

```bash
# OIDC
ENGRAM_SSO_OIDC_ENABLED=true
ENGRAM_SSO_GOOGLE_CLIENT_ID=...
ENGRAM_SSO_GOOGLE_CLIENT_SECRET=...

# SAML
ENGRAM_SSO_SAML_ENABLED=true
ENGRAM_SSO_SAML_IDP_CERT=...
```

## Enforcement

| Setting | Behavior |
|---------|----------|
| SSO Required | All users must authenticate via SSO |
| JIT Provisioning | Auto-create user on first SSO login |
| Group Mapping | Map IdP groups to Engram roles |
| Domain Restriction | Restrict to specific email domains |

## Roadmap

| Phase | Feature | Timeline |
|-------|---------|----------|
| 1 | OIDC (Google, Okta) | Q3 2026 |
| 2 | SAML 2.0 | Q4 2026 |
| 3 | JIT Provisioning | Q1 2027 |
| 4 | Group Mapping | Q1 2027 |

## Related Documentation

- [PRIVACY_ARCHITECTURE.md](./PRIVACY_ARCHITECTURE.md)
- [DATABASE_SECURITY.md](./DATABASE_SECURITY.md)
- [IMPLEMENTATION.md](./IMPLEMENTATION.md)
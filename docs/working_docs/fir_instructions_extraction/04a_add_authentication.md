
# Task 04a: Add Authentication

## Goal

Add authentication to the FastAPI app:
* Approach should be to use OAuth2 with Password (and hashing) for login and then Bearer with JWT tokens for API calls
* Set up a Keycloak container in docker compose to handle the OAuth2 accounts (this will allow for other services to use the same auth provider later)
* For development purposes, the app should launch with a default admin user with a documented username and password
* A new task document should be started to note additional steps needed to make the auth production-ready. Those steps should not be implemented in this task unless they are easy to do.

Permission levels to include:
- Viewer: can request data only (read-only), and manage their own account
- Editor: can edit data; plus all privileges of Viewer
- Administrator: can manage users; plus all privileges of Editor

## Task List

## Implementation Details

## Tests

## Documentation Updates

## Success Criteria

## Verification

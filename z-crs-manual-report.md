# CRS Manual Tests Report

## Test Environment

- alpha.7

- PASS set Maximum login attempts before account deactivation to 2 and see that after 2 fails
on ODD and on APP the account is deactivated and the user is locked out.
- FAIL Click into the logins input, then click out of it.  The user should not see the audit documentation prompt because they did not change the value. - 9/3/2026 state is that the audit documentation modal is shown like the user is changing the value.
- PASS toggle the Require password to be changed after a certain amount of time to true.  After that time goes by see that users are required to 


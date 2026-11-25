# Security policy

Leonida V downloads files, runs mod installers and writes into your game folder, so we take security problems
seriously. Thank you for reporting them responsibly.

## Report a problem privately

**Please don't open a public issue, discussion or pull request for a security problem.**

Use GitHub's private reporting: go to the repository's **Security** tab → **Report a vulnerability**
(<https://github.com/JacobJandon/leonida-v/security/advisories/new>). Only the maintainers see the report.

Please include:

- what the problem is and what an attacker could do with it;
- the steps to reproduce it (a small proof of concept is great), and the Leonida V version;
- whether it needs anything special (a malicious mod archive, a man-in-the-middle, a local account).

We'll answer within **7 days**, keep you updated, and credit you in the release notes when it's fixed (unless you'd
rather stay anonymous). Please give us a reasonable time to release a fix before telling others.

## What counts

In scope, for example:

- a downloaded archive that can write outside the folder it's extracted into (path traversal, links);
- the self-updater or setup accepting a file that isn't the published release (checksums, signatures, downgrade);
- Leonida fetching a mod from somewhere other than the author's source written in the manifest;
- the in-game menu bridge (`<state>/menu/`) being used to make Leonida write files it shouldn't;
- private details (user name, paths, keys) left in a `leonida report` zip.

Not in scope: bugs in the mods themselves (please report those to their authors), the game, or anything about
GTA Online (Leonida is story mode only and never supports online play).

## Supported versions

Security fixes go into the latest release. Installed copies update themselves (*Manage* → *Check for updates*, or
`leonida self-update`).

# Contributing to OpenLearn

Thanks for helping. OpenLearn is a learning platform meant to stay free and
self-hostable, and every contribution is expected to keep it that way.

## Ground rules

- **English everywhere in the repository**: code, comments, commit messages,
  documentation and test names. The user interface is translated, the code is
  not.
- **No new dependency without a reason.** Each one has to be compatible with the
  AGPL: MIT, BSD, Apache-2.0, ISC and LGPL-3 are fine. GPL-2-only, SSPL and
  "source available" licences are not.
- **No vendored code.** Adding a third-party file means adding its licence and
  its notice, and that is a decision to discuss in an issue first.
- **Tests come with the change.** A bug fix gets a test that fails without it;
  a feature gets the tests that describe what it promises.
- **Every source file starts with the licence header** (`SPDX-License-Identifier:
  AGPL-3.0-only`). There is no exception and no exemption for "small" files.

## Before opening a pull request

```bash
python -m pytest -q            # the backend suite
node --check frontend/js/app.js  # the frontend has no build step
```

The full suite also runs against a throwaway instance:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm tests
```

## Contributor Licence Agreement

Before a pull request can be merged, you need to sign the CLA in
[CLA.md](CLA.md). It is a short document: you keep the copyright on what you
write, and you grant the project the right to distribute your contribution,
including under a different licence if the project ever needs to.

That second part matters. OpenLearn may one day offer a commercial licence to
companies that cannot use the AGPL, and that is only possible if the project
holds enough rights over every line in the repository. Accepting contributions
without those rights would lock the project into its current licence forever.

Signing is one comment on your first pull request:

> I have read the CLA in CLA.md and I agree to its terms for my contributions to
> this project.

## Reporting a security issue

Do not open a public issue. Follow [SECURITY.md](SECURITY.md).

## Code of conduct

Argue about code, not about people. Contributions are judged on what they do,
not on who wrote them.

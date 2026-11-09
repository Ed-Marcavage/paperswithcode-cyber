# 0security repository addition

Adds one repository entry, `0sec-labs/0`, and its owning organization,
`0security`. It is a repository, not a research paper or engineering post.

The [README at the reviewed revision](https://github.com/0sec-labs/0/blob/5169ae22d7fc339730b93a963441955086a57a56/README.md)
describes reusable security workflows, CLI/MCP access, verification and fixes,
and Ghidra-based binary analysis. Those capabilities support the existing
vulnerability analysis, penetration testing, binary analysis and repair topics;
source code and native binaries are the target facets. The contribution is a
system. These tags describe scope, not independently measured effectiveness.
The description is an original catalog summary. No third-party text or artwork
is redistributed in this seed.

GitHub identifies the owner as an organization (ID `274613126`) and the repository
as ID `1339271188`. There is no publication date: repository creation and commit
timestamps do not establish a paper or blog publication date. The upstream
README identifies the project as a research preview and links MIT/Apache-2.0
licenses. Its [research index](https://0.security/research/) is a separate source;
this batch does not create a blog entry from the repository.

Import into the running local catalog, using fresh GitHub star counts:

```sh
sh local-dev/compose.sh exec -T backend python -m local-dev.import_catalog /app/local-dev/seeds/zero-security/catalog.json --append --execute
sh local-dev/compose.sh exec -T backend python -m local-dev.repository_catalog /app/local-dev/seeds/zero-security/repositories.json --fetch-current --execute
sh local-dev/compose.sh exec -T backend python -m local-dev.import_catalog_organizations /app/local-dev/seeds/zero-security/organizations.json --execute
```

Refresh developer snapshots with the collector documented in
[the local setup notes](../../README.md#developers), then import them. The
organization is not a developer account. Only the public GitHub user
contributors appear in Developers; bots are excluded. Contributor counts do not
establish paper authorship or employment. Code, catalog seeds and developer
snapshots are separate release inputs.

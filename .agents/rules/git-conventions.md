---
trigger: always_on
---

---
trigger: always_on
---

# Git Conventions

## Branching Conventions

Each repo must have these 3 main/long-lived branches:
1. `main` / `master`
2. `staging`
3. `dev`

Except for Hotfixes, code changes must follow a one-way merge flow starting from:
`temporary-branch` > `dev` > `staging` > `main`

### Temporary Branches

Create a new branch every time you are working on something. Branch names should start with the username, followed by a slash, the category, the ticket number, and a brief description in kebab-case.

**Format:** `<username>/<category>/<ticket-number>-<branch-name-in-kebab-case>`

#### Categories:

| Category | Description |
| :--- | :--- |
| `feature` | For adding, refactoring, or removing a feature |
| `bugfix` | For fixing a bug |
| `hotfix` | For changing code with a temporary solution and/or without following the usual process (usually because of an emergency) |
| `test` | For experimenting outside of an issue/ticket |
| `wip` | For work-in-progress tasks |

#### Examples:

1. Add, refactor, or remove a feature:
   `git branch zaeema/feature/GEN-120-create-new-button-component`

2. Fix a bug:
   `git branch awa/bugfix/GEN-121-button-overlap-form-on-mobile`

3. Fix a bug really fast (possibly with a temporary solution):
   `git branch hamza/hotfix/GEN-122-registration-form-not-working`

4. Experiment outside of an issue/ticket:
   `git branch musa/test/GEN-123-refactor-components-with-atomic-design`

5. Work-in-progress on a lengthy task:
   `git branch laraib/wip/GEN-124-change-onboarding-flow`

---

## Commit Conventions

1. Commits MUST be prefixed with a type, which consists of a noun (e.g., `FEAT`, `FIX`), followed by an OPTIONAL scope, OPTIONAL `!`, and REQUIRED terminal colon and space.
2. The type `FEAT` MUST be used when a commit adds a new feature to your application or library.
3. The type `FIX` MUST be used when a commit represents a bug fix for your application.
4. A scope MAY be provided after a type. A scope MUST consist of a noun describing a section of the codebase surrounded by parenthesis, e.g., `FIX(parser):`.
5. A description MUST immediately follow the colon and space after the type/scope prefix. The description is a short summary of the code changes, e.g., `FIX: array parsing issue when multiple spaces were contained in string`.
6. A longer commit body MAY be provided after the short description, providing additional contextual information about the code changes. The body MUST begin one blank line after the description.
7. A commit body is free-form and MAY consist of any number of newline-separated paragraphs.
8. One or more footers MAY be provided one blank line after the body. Each footer MUST consist of a word token, followed by either a `: ` or ` #` separator, followed by a string value (inspired by the git trailer convention).
9. A footer's token MUST use `-` in place of whitespace characters, e.g., `Acked-by` (this helps differentiate the footer section from a multi-paragraph body). An exception is made for `BREAKING CHANGE`, which MAY also be used as a token.
10. A footer's value MAY contain spaces and newlines, and parsing MUST terminate when the next valid footer token/separator pair is observed.
11. Breaking changes MUST be indicated in the type/scope prefix of a commit, or as an entry in the footer.
12. If included as a footer, a breaking change MUST consist of the uppercase text `BREAKING CHANGE`, followed by a colon, space, and description, e.g., `BREAKING CHANGE: environment variables now take precedence over config files`.
13. If included in the type/scope prefix, breaking changes MUST be indicated by a `!` immediately before the `:`. If `!` is used, `BREAKING CHANGE:` MAY be omitted from the footer section, and the commit description SHALL be used to describe the breaking change.
14. Types other than `feat` and `fix` MAY be used in your commit messages, e.g., `docs: update ref docs.`
15. The units of information that make up Conventional Commits MUST NOT be treated as case sensitive by implementors, with the exception of `BREAKING CHANGE` which MUST be uppercase.
16. `BREAKING-CHANGE` MUST be synonymous with `BREAKING CHANGE` when used as a token in a footer.

### Commit Prefixes

| Prefix | Description |
| :--- | :--- |
| `FEAT` | When a new feature is added/removed |
| `FIX` | When a bug is fixed |
| `HOTFIX` | For quick hotfixes on production |
| `CHORE` | Changes to the build process or auxiliary tools and libraries |
| `REFACTOR` | Refactoring code (changes that have no effect on UI/functionality) |
| `DOCS` | Documentation changes only (README.md etc.) |
| `!` | Add after prefix to represent breaking changes in commit. E.g., `REFACTOR!: Added Aliasing` |

### Examples

**Commit message with description and breaking change footer:**
```
FEAT: allow provided config object to extend other configs

BREAKING CHANGE: `extends` key in the config file is now used for extending other config files
```

**Commit message with `!` to draw attention to breaking change:**
```
FEAT!: send an email to the customer when a product is shipped
```

**Commit message with scope and `!` to draw attention to breaking change:**
```
FEAT(api)!: send an email to the customer when a product is shipped
```

**Commit message with both `!` and BREAKING CHANGE footer:**
```
CHORE!: drop support for Node 6

BREAKING CHANGE: use JavaScript features not available in Node 6.
```

**Commit message with no body:**
```
DOCS: correct spelling of CHANGELOG
```

**Commit message with scope:**
```
FEAT(lang): add Polish language
```

**Commit message with multi-paragraph body and multiple footers:**
```
FIX: prevent racing of requests

Introduce a request id and a reference to latest request. Dismiss
incoming responses other than from latest request.

Remove timeouts which were used to mitigate the racing issue but are
obsolete now.

Reviewed-by: Z
Refs: #123
```

---

## Pull Request / Merge Request Conventions

### Merge Flow

Don't open a pull request directly to the `main`/`master` branch of the project. A PR should follow the one-way merge flow (`temporary-branch` > `dev` > `staging` > `main`).
It's recommended not to skip any step. **Never** push directly to `dev`, `staging`, or `main` branch.

### Feature Branch Workflow:

1. Create a separate feature branch for working on a feature.
2. Create a pull request (PR) to merge the feature branch into the `dev` branch.
3. Add 2 reviewers to the PR.
4. Require approval from at least 1 reviewer to merge the PR into the `dev` branch.
5. Delete the feature branch after the PR is merged.

### Merge Strategy:

1. **Merge without squashing** if the PR includes changes beyond the feature's branch scope (multiple changes/branches) to retain commit history.
2. **Squash and merge** if the PR contains only feature-specific changes to keep the commit history clean.

### Review

Each development pull request should be approved by at least two team members, ideally one senior and one junior with relevant expertise, before it can be merged.

### PR Title & Description Format

Start the PR title with your branch category in **UPPERCASE**. For the description, use the applicable PR template:

#### For backend repositories:

```markdown
### Task Details
- **JIRA Ticket #:** [Ticket Number]
- **Ticket Link:** [Ticket Link]

### Checklist
  - [ ] Functions, classes, and modules have clear names and comments/documentation.
  - [ ] Ticket number and your name are included in branch name.
  - [ ] Screenshots for Django Debug Toolbar/Silk have been attached.
```

#### For frontend repositories:

```markdown
### Task Details
- **JIRA Ticket #:** [Ticket Number]
- **Ticket Link:** [Ticket Link]

### Checklist
  - [ ] Functions, classes, and modules have clear names and comments/documentation.
  - [ ] Ticket number and your name are included in branch name.
  - [ ] UI screenshots have been attached.
```

An `x` between the square brackets marks it as checked and a space leaves it unchecked.
- `[x]` checked
- `[ ]` unchecked

---

## References

1. **Conventional Commits:** https://www.conventionalcommits.org/en/v1.0.0/
2. **Branch name conventions:** https://dev.to/varbsan/a-simplified-convention-for-naming-branches-and-commits-in-git-il4

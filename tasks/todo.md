# PDF cleanup plan

- [x] Review tracked PDF files and classify which should remain in Git
- [x] Update `.gitignore` so only servitutredegørelser and tinglysningsattester can be tracked as PDFs
- [x] Remove other tracked PDFs from the Git index without deleting local files
- [x] Verify the staged diff and document the result

## Review

- `.gitignore` now ignores all `*.pdf` files except filenames containing `Servitutredegørelse` or `Tinglysningsattest`
- 30 tracked PDF files were removed from the Git index with `git rm --cached`, leaving the local files in place
- Remaining step outside this workspace change is to commit and push the staged deletions so the files disappear from the remote repository

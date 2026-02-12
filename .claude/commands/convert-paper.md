---
allowed-tools: mcp__pdf2md-service__pdf2md_submit, mcp__pdf2md-service__pdf2md_status, mcp__pdf2md-service__pdf2md_retrieve
---

Convert the PDF at `$ARGUMENTS` to markdown using the pdf2md homelab service.

Steps:
1. Submit the PDF with `pdf2md_submit` (use depth "medium" unless the user specifies otherwise).
2. Poll `pdf2md_status` every 5 seconds until status is "completed" or "failed".
   - Print each status change so the user can see progress.
3. If completed, call `pdf2md_retrieve` to download results to a directory next to the PDF (same name without extension).
4. Report the list of extracted files and their location.

If the job fails, show the error message and stop.

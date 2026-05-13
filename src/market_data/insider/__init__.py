"""SEC Form 4 insider-transaction ingestion + parsing.

Form 4 is filed within 2 business days of any insider open-market
transaction. The parsed records back the ``insider_flow`` analyzer,
which scores stocks on Cohen-Malloy-Pomorski-style cluster buys
(multiple insiders independently buying within a short window).

Modules:
  - ``client``: extends EDGARClient with Form 4 listing + document fetch
  - ``parser``: pure XML → InsiderTransaction records
  - ``ingest``: orchestrator (CIK → filings → parse → upsert)
"""

alter table public.documents
  drop constraint if exists documents_doc_type_check;

alter table public.documents
  add constraint documents_doc_type_check
  check (doc_type in ('pdf', 'docx', 'txt', 'csv', 'pptx', 'json', 'url'));

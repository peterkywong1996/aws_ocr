# aws_ocr
Amazon Textract for OCR on ID Cards
- Code logic:
- 1) User uploaded images to S3 database
  2) Automatically triggered lambda_handler()
  3) Triggered scan_worker_card() to retrieve the uploaded images
  4) Compare with existing data in S3 database to decide INSERT new data or MODIFY existing data
  5) Triggered textract_extract_queries() to obtain OCR results, with post-processing
  6) Link to the database for automatic record updating
- Codes that may involve customization:
- - get_qa_map(): QueriesConfig -> a list of queries/prompts to govern what information to search from an image; currently extracted = worker name, card reference number, validity period, certificate type
- scan_worker_card(): update_item -> the list of updates should be modified according to those queried above

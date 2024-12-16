# aws_ocr
Amazon Textract for OCR on ID Cards
- Code logic:
- 1) User uploaded images to S3 database
  2) Automatically triggered lambda_handler()
  3) Triggered scan_worker_card() to retrieve the uploaded images
  4) Compare with existing data in S3 database to decide INSERT new data or MODIFY existing data
  5) Triggered textract_extract_queries() to obtain OCR results, with post-processing
  6) Expected output a JSON structure (refer to sample text files)
  7) Link to the database for automatic record updating

- How to run the code (both required an AWS account):
- Option A. Configuration on AWS cloud:
     1) Upload the .py code to AWS Lambda as a new function
     2) Define your own S3 & DynamoDB objects
     3) Configure trigger(s) to link up the Lambda function with S3 & DynamoDB
     4) Customize the variable names according to your own data schema
  
- Option B. Configuration on local computer (https://boto3.amazonaws.com/v1/documentation/api/latest/guide/quickstart.html#installation):
     1) Install python packages on local computer
     2) Input your own AWS authentication creditials
     3) Similar to the cloud-based steps

- Codes that may involve customization:
- - get_qa_map(): QueriesConfig -> a list of queries/prompts to govern what information to search from an image; currently extracted = worker name, card reference number, validity period, certificate type
- - scan_worker_card(): update_item -> the list of updates should be modified according to those queried above

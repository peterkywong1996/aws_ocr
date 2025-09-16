# Basic python packages
from decimal import Decimal
import json
import urllib.request
import urllib.parse
import urllib.error
import time
from datetime import datetime

# For using Textract
import boto3
import base64
import logging
import sys
import re
from collections import defaultdict
from botocore.exceptions import ClientError


#------Initialize the AWS API objects------
s3_client = boto3.client('s3', region_name='ap-southeast-1')
textract_client = boto3.client('textract', region_name='ap-southeast-1')


#------Helper functions for calling Textract.analyze_document() to extract query-answer (qa) pairs------

def find_answer_block(query_block, answer_map):
    answer_block = None
    if 'Relationships' in query_block.keys():
        for relationship in query_block['Relationships']:
            if relationship['Type'] == 'ANSWER':
                for answer_id in relationship['Ids']:
                    answer_block = answer_map[answer_id]
    return answer_block

def get_query_text(result, blocks_map):
    text = None
    if result is not None:
        blockType = result['BlockType']
        if blockType == 'QUERY':
            text = result['Query']['Alias']
        elif blockType == 'QUERY_RESULT':
            text = result['Text']
        else:
            text = ''
    return text

def get_qa_relationship(query_map, answer_map, block_map):
    qas = defaultdict(list)
    for block_id, query_block in query_map.items():
        answer_block = find_answer_block(query_block, answer_map)
        query = get_query_text(query_block, block_map)
        answer = get_query_text(answer_block, block_map)
        qas[query].append(answer)
    return qas

#------User-defined list of queries in QueriesConfig to govern what information to search for------
def get_qa_map(object):
    response = textract_client.analyze_document(
        Document={'Bytes': object}, FeatureTypes=['QUERIES'],
        QueriesConfig={'Queries':[
            {'Text': 'English name of the holder?', 'Alias': 'Name'},
            {'Text': 'Chinese name of the holder?', 'Alias': 'Name_Chi'}, # As of 16 Sep 2025, AWS Textract may NOT support Chinese words
            {'Text': 'Reference no. of registration card?', 'Alias': 'No.'},
            {'Text': 'Validity period from?', 'Alias': 'DateFrom'},
            {'Text': 'Validity period to?', 'Alias': 'DateTo'},
            {'Text': 'Expiry date?', 'Alias': 'ExpiryDate'},
            {'Text': 'Type of certificate?', 'Alias': 'Type'}
    ]})
    
    # Get the text blocks
    blocks = response['Blocks']

    # get key and value maps
    query_map = {}
    answer_map = {}
    block_map = {}
    for block in blocks:
        block_id = block['Id']
        block_map[block_id] = block
        if block['BlockType'] == "QUERY":
            query_map[block_id] = block
        elif block['BlockType'] == "QUERY_RESULT":
            answer_map[block_id] = block
        else:
            continue
    
    return query_map, answer_map, block_map

def textract_extract_queries(bucket, key):
    s3_object = s3_client.get_object(Bucket=bucket, Key=key)
    query_map, answer_map, block_map = get_qa_map(s3_object['Body'].read())
    #refer to get_qa_map, where users can define own list of queries (what information to search from an image)
    
    # Get Query-Answer relationships
    qas = get_qa_relationship(query_map, answer_map, block_map)
    print_kvs(qas)
    
    return qas


#------Helper functions------

def date_2_time(date, fmt='%d/%m/%Y'):
    return int(datetime.timestamp(datetime.strptime(date.group(), fmt)))

# for handling the uncertain results  validity dates
def extract_date(date):
    date_extracted = None
    valid = None
    if date is not None:
        date_extracted = re.search(r'\d{2}/\d{2}/\d{4}', date)
        if date_extracted is not None:
            date_extracted = date_2_time(date_extracted)
            valid = True
        else:
            date_extracted = re.search(r'\d{2}-\d{2}-\d{4}', date)
            if date_extracted is not None:
                date_extracted = date_2_time(date_extracted, '%d-%m-%Y')
                valid = True
            else:
                date_extracted = int(time.time())
                valid = False
    else:
        date_extracted = int(time.time())
        valid = False
    
    return date_extracted, valid
    

#---------------------------
def scan_worker_card(event):

    id = event['Records'][0]['dynamodb']['NewImage']['id']['S']
    card_url_new = event['Records'][0]['dynamodb']['NewImage']['workerProfile']['M']['cardImages']['L'][0]['S']
    eventName = event['Records'][0]['eventName'] #Possible cases: INSERT, MODIFY

    if eventName == 'MODIFY': #existing data available, no need to create new entry -> retrieve old data first for later matching
        card_url_old = event['Records'][0]['dynamodb']['OldImage']['workerProfile']['M']['cardImages']['L'][0]['S']
        if card_url_old == card_url_new:
            return None
        
        displayName_old = event['Records'][0]['dynamodb']['OldImage']['displayName']['S']
        chineseName_old = event['Records'][0]['dynamodb']['OldImage']['chineseName']['S'] # As of 16 Sep 2025, AWS Textract may NOT support Chinese words
        refNo_old = event['Records'][0]['dynamodb']['OldImage']['workerProfile']['M']['refNo']['S']
        certificates_old = event['Records'][0]['dynamodb']['OldImage']['workerProfile']['M']['certificates']
    
    card_directory = card_url_new.split('bucketName=')[1] #get the full directory path
    bucket, key = card_directory.split('&fileName=') #get the folder and filename respectively
    #sample output for illustration only: bucket, key = 'autofill-worker-card-images', '0001.png'
    
    #---finished preparation of the image for processing---

    #---start calling AWS Textract for OCR on the image---
    response_textract = textract_extract_queries(bucket, key)

    #---store each OCR result for post-processing---
    displayName = response_textract['Name'][0]
    chineseName = response_textract['Name_Chi'][0] # As of 16 Sep 2025, AWS Textract may NOT support Chinese words
    refNo = response_textract['No.'][0]
    validityFrom = response_textract['DateFrom'][0]
    validityTo = response_textract['DateTo'][0]
    expiryDate = response_textract['ExpiryDate'][0]
    certificate = response_textract['Type'][0]
    
    # Validity period --> handle uncertain OCR results
    validityFrom, _ = extract_date(validityFrom)
    validityTo, dateValid1 = extract_date(validityTo)
    expiryDate, dateValid2 = extract_date(expiryDate)
    
    if dateValid1 and dateValid2:
        expiryDate = max(expiryDate, validityTo)
    elif dateValid1 and not dateValid2:
        expiryDate = validityTo
    
    # Append more certificates on top of old list if same name & id
    certificates = []
    if eventName == 'MODIFY':
        if displayName_old == displayName and refNo_old == refNo:
            if certificates_old is not None:
                if 'S' in certificates_old.keys():
                    certificate_old = certificates_old['S']
                    if certificate_old != certificate:
                        certificates.append(certificate_old)
                elif 'L' in certificates_old.keys():
                    for certificate_old in certificates_old['L']:
                        if certificate_old['S'] != certificate:
                            certificates.append(certificate_old['S'])
    certificates.append(certificate)
    
    #---access the database to prepare for record updating---
    table = boto3.resource('dynamodb').Table('users')
    
    #---require manual modification if more information are queried---
    #---currently extracted info: reference no., validity periods, certificate types---
    # As of 16 Sep 2025, AWS Textract may NOT support Chinese words
    try:
        response = table.update_item(
            Key={'accountType': 'worker', 'id': id},
            UpdateExpression=' \
                set displayName=:n, \
                chineseName=:z, \
                workerProfile.refNo=:r, \
                workerProfile.validityFrom=:f, \
                workerProfile.validityTo=:t, \
                workerProfile.expiryDate=:d, \
                workerProfile.certificates=:c',
            ExpressionAttributeValues={
                ':n': displayName,
                ':z': chineseName,
                ':r': refNo,
                ':f': validityFrom,
                ':t': validityTo,
                ':d': expiryDate,
                ':c': certificates
            },
            ReturnValues="UPDATED_NEW",
        )
    except ClientError as err:
        raise
    
    return response


# --------------- Main handler ------------------

def lambda_handler(event, context):
    try:
        response = scan_worker_card(event)
        return response
        
    except Exception as e:
        raise e

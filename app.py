import json
import re
from urllib import request
from kubernetes import client, config
import subprocess
import pymysql
import pymysql.cursors
from fastapi import Body, FastAPI, Request, status, File, UploadFile, Form, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import logging
import uvicorn
import os
import requests



app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
    expose_headers=['*']
)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__file__)
logger.setLevel(logging.DEBUG)

clustername = os.environ.get('CLUSTER_NAME')
clusterzone = os.environ.get('CLUSTER_ZONE')
clusterproject = os.environ.get('PROJECT_ID')
host = os.environ.get('MICRO_DB_HOST')
name = os.environ.get('MICRO_DB_USERNAME')
password = os.environ.get('MICRO_DB_PASSWORD')
db_name =  os.environ.get('MICRO_DB_DATABASE')
gke = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

def sql_conn():
    try:
        conn = pymysql.connect(host=host, user=name, passwd=password, db=db_name, charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor)
        return conn
    except Exception as e: 
        logger.error(str(e))


@app.post('/check_resource_availability',status_code = 200)
async def main(request:Request):
    try:        
        req_json=await request.json()
        logger.info(req_json)
        rtn_msg = {}

        if 'x-api-key' not in req_json or 'fun_code' not in req_json:
            rtn_msg["status"] = "Failure"
            rtn_msg["message"] = "Input Field Missing"
            status_code = 419
            return JSONResponse(status_code=status_code, content=rtn_msg)

        # owner_id = req_json["owner_id"]
        f_code = req_json["fun_code"]
        api_key = req_json["x-api-key"]
        owner_id =  get_owner_id(api_key)
        logger.info(owner_id)
        resource_availability = True 

        logger.info("Fetching owner details")
        nsdetails_querry = "SELECT * FROM owner_settings where OWNER_ID=%s and STATUS='A';"
        
        conn = sql_conn()
        cursor = conn.cursor()
        cursor.execute(nsdetails_querry,owner_id)
        cursor.close()
        result = cursor.fetchall()
        
        if result == ():
            result_msg = {'availability' : False}
            rtn_msg["results"] = result_msg
            rtn_msg["status"] = "Failure"
            rtn_msg["message"] = "Invalid Owner ID"
            status_code = 415
            return JSONResponse(status_code=status_code, content=rtn_msg)
            
        org_det = result[0]

        logger.info(org_det)
        logger.info("Owner details Fetched")

        # Allocated rescource for NS from DB

        namespace = org_det['OWNER_CODE']
        all_mem = int(org_det['TOTAL_MEMORY'])
        all_cpu = int(org_det['TOTAL_CPU'])
        all_gpu = int(org_det['TOTAL_GPU'])


        total_ai_ms = org_det["TOTAL_NUMBER_OF_AI"]
        total_non_ai_ms = org_det["TOTAL_NUMBER_OF_NONAI"]
        total_data_ms = org_det["TOTAL_NUMBER_OF_DA"]
        

        avl_ai_ms = org_det["AVAILABLE_NUMBER_OF_AI"]
        avl_non_ai_ms = org_det["AVAILABLE_NUMBER_OF_NONAI"]
        avl_data_ms = org_det["AVAILABLE_NUMBER_OF_DA"]

        if (avl_ai_ms >= total_ai_ms) or (avl_non_ai_ms >= total_non_ai_ms) or (avl_data_ms >= total_data_ms):

            result_msg = {'availability' : False}
            rtn_msg["results"] = result_msg
            rtn_msg["status"] = "Failure"
            rtn_msg["message"] = "Reached max number of microservice"
            status_code = 406
            return JSONResponse(status_code=status_code, content=rtn_msg)

        msdetails_querry = "SELECT ft.* FROM function_training ft,function f where ft.STATUS='A' and ft.FUN_ID=f.ID and f.CODE=%s"

        conn = sql_conn()
        cursor = conn.cursor()
        cursor.execute(msdetails_querry,(f_code))
        cursor.close()
        result = cursor.fetchall()
        logger.info(result)
        if len(result) > 0:
            ms_detail = result[0]
        
            logger.info(ms_detail)
            req_cpu = int(ms_detail["CPU"])
            req_mem = int(ms_detail["MEMORY"])
            req_gpu = int(ms_detail["GPU"])
            topic_id = ms_detail["TOPIC_ID"]
            func_code = ms_detail["FUN_CODE"]
            version = ms_detail["VERSION"]
            gpu_type = ms_detail["GPU_TYPE"]
            

            if topic_id == "null" or topic_id is None:
                topic_id = ""

            used = used_rescource_by_ns(clustername,clusterzone,clusterproject,namespace)

            logger.info("Total Used CPU: "+str(used['cpu']))
            logger.info("Total Used Memeory: "+str(used['mem']))
            logger.info("Total Used GPU: "+str(used['gpu']))
            logger.info("=============================================")
            logger.info("Total Requested Memeory: "+str(req_mem))
            logger.info("Total Requested CPU: "+str(req_cpu))
            logger.info("Total Requested GPU: "+str(req_gpu))


            if req_mem > (all_mem - used['mem']):
                logger.info('mem not available')
                logger.info('allocated : ' + str(all_mem) + ', used : '+str(used['mem']) + ', requsted : ' +str(req_mem) + ', available : '+str(all_mem - used['mem']))
                resource_availability = False

            if req_cpu > (all_cpu - used['cpu']):
                logger.info('cpu not available')
                logger.info('allocated : ' + str(all_cpu) + ', used : '+str(used['cpu']) + ', requsted : ' +str(req_cpu) + ', available : '+str(all_cpu - used['cpu']))
                resource_availability = False

            if req_gpu > (all_gpu - used['gpu']):
                logger.info('gpu not available')
                logger.info('allocated : ' + str(all_gpu) + ', used : '+str(used['gpu']) + ', requsted : ' +str(req_gpu) + ', available : '+str(all_gpu - used['gpu']))
                resource_availability = False

            result_msg = {'availability' : resource_availability,'available_gpu' : all_gpu - used['gpu'] , 'available_mem' : all_mem - used['mem'] , 'available_cpu' : all_cpu - used['cpu'] , 'topic_id' : topic_id , 'namespace' : namespace , 'fun_code' : func_code ,"version" : version , "gpu_type" : gpu_type}
            rtn_msg["results"] = result_msg
        else:
            result_msg = {'availability' : False}
            rtn_msg["results"] = result_msg


        rtn_msg["status"] = "Success"
        rtn_msg["message"] = "Successfully Processed"

        logger.info('availability : ' + str(resource_availability))   
        return JSONResponse(status_code=200, content=rtn_msg)
    
    except Exception as e:
        logger.error(e)
        rtn_msg["status"] = "Failures"
        rtn_msg["message"] = str(e)
        return JSONResponse(status_code=500, content=rtn_msg)

@app.post('/check_path',status_code = 200)
async def check_model(request:Request):
    try:
        req_json=await request.json()
        logger.info(req_json)
        rtn_msg = {}
        
        if 'x-api-key' not in req_json or 'fun_code' not in req_json  or 'path' not in req_json:
            
            rtn_msg["status"] = "Failure"
            rtn_msg["message"] = "Input Field Missing"
            status_code = 419
            logger.info(status_code)
            logger.info(rtn_msg)
            return JSONResponse(status_code=status_code, content=rtn_msg)

        api_key = req_json["x-api-key"]
        f_code = req_json["fun_code"]

        user_det_querry = "select * from user where API_KEY=%s and STATUS='A' "

        conn = sql_conn()
        cursor = conn.cursor()
        cursor.execute(user_det_querry,api_key)
        cursor.close()
        result = cursor.fetchall()
        user_det = result[0]

        user_id = user_det['ID']
        logger.info(user_id)
        

        fun_code = req_json["fun_code"]
        path = req_json["path"]

        selectQuery = "SELECT fm.* FROM function_trained_model fm ,function f WHERE fm.STATUS='A' and fm.USER_ID=%s and fm.FUN_ID=f.ID and f.CODE='%s' and  fm.ENDPOINT='%s'"
        conn = sql_conn()
        cursor = conn.cursor()
        cursor.execute(selectQuery%(user_id,fun_code,path))
        result = cursor.fetchall()

        logger.info(result)

        if len(result)>0:
            result_msg = {'path_exists' : True}
            
        else:
            result_msg = {'path_exists' : False}
        
        rtn_msg["results"] = result_msg
        rtn_msg["status"] = "Success"
        rtn_msg["message"] = "Successfully Processed"

        logger.info(result_msg)
        return JSONResponse(status_code=200, content=rtn_msg)

    except Exception as e:
        logger.error(e)

        rtn_msg["status"] = "Failure"
        rtn_msg["message"] =  str(e)
        return JSONResponse(status_code=500, content=rtn_msg)


@app.post('/update_resource',status_code = 200)
async def update_resource(request:Request):
    
    try:
        req_json=await request.json()
        logger.info(req_json)
        rtn_msg = {}

        rtn_msg["status"] = "Success"
        rtn_msg["message"] = "Successfully Processed"
        status_code = 200

        if 'x-api-key' not in req_json or 'fun_type' not in req_json:    
            result_msg = {'availability' : False}
            rtn_msg["results"] = result_msg
            rtn_msg["status"] = "Failure"
            rtn_msg["message"] = "Input Field Missing"
            status_code = 419
            logger.info(rtn_msg)
            return JSONResponse(status_code=status_code, content=rtn_msg)
        

        api_key = req_json["x-api-key"]
        owner_id =  get_owner_id(api_key)
        f_type = req_json["fun_type"]
        # f_code = req_json["fun_code"]
        # version = req_json["version"]
        # path = req_json["path"]
        logger.info(owner_id)

        logger.info("Fetching Owner details")

        get_ns_querry = "SELECT * FROM owner_settings where OWNER_ID=%s and STATUS='A';"
        conn = sql_conn()
        cursor = conn.cursor()
        cursor.execute(get_ns_querry,owner_id)
        cursor.close()
        result = cursor.fetchall()

        if result == ():
            result_msg = {'availability' : False}
            rtn_msg["results"] = result_msg
            rtn_msg["status"] = "Failure"
            rtn_msg["message"] = "Invaild owner id or data isn't available"
            status_code = 415
            logger.info(rtn_msg)
            return JSONResponse(status_code=status_code, content=rtn_msg)

        org_det = result[0]
        logger.info(org_det)
        logger.info("Owner details Fetched")

        # Allocated rescource for NS from DB

        namespace = org_det['OWNER_CODE']
        all_mem = int(org_det['TOTAL_MEMORY'])
        all_cpu = int(org_det['TOTAL_CPU'])
        all_gpu = int(org_det['TOTAL_GPU'])

        if f_type == "ai":
            ms_type = "AVAILABLE_NUMBER_OF_AI"
            total_ms = int(org_det['TOTAL_NUMBER_OF_AI'])
            avl_ms = int(org_det['AVAILABLE_NUMBER_OF_AI'])


        elif f_type == "non_ai":
            ms_type = "AVAILABLE_NUMBER_OF_NONAI"
            total_ms = int(org_det['TOTAL_NUMBER_OF_NONAI'])
            avl_ms = int(org_det['AVAILABLE_NUMBER_OF_NONAI'])

        elif f_type == "data":
            ms_type = "AVAILABLE_NUMBER_OF_DA"
            total_ms = int(org_det['TOTAL_NUMBER_OF_DA'])
            avl_ms = int(org_det['AVAILABLE_NUMBER_OF_DA'])

        else:
            result_msg = {'availability' : False}
            rtn_msg["results"] = result_msg
            rtn_msg["status"] = "Failure"
            rtn_msg["message"] = "Invaild Function type"
            status_code = 415
            return JSONResponse(status_code=status_code, content=rtn_msg)

        current_avl_ms = avl_ms + 1 
        used = used_rescource_by_ns(clustername,clusterzone,clusterproject,namespace)


        nsdetails_update_querry = "UPDATE owner_settings SET "+ms_type+"=%s ,AVAILABLE_MEMORY=%s,AVAILABLE_CPU=%s,AVAILABLE_STORAGE=%s,AVAILABLE_GPU=%s where OWNER_ID=%s;"
        
        logger.info("Updating Resource utilised")
        conn = sql_conn()
        cursor = conn.cursor()
        cursor.execute(nsdetails_update_querry%(str(current_avl_ms),str(all_mem - used['mem']),str(all_cpu - used['cpu']),str(used['mem']),str(all_gpu - used['gpu']),owner_id))
        conn.commit()
        cursor.close()


        res = {'available_gpu' : all_gpu - used['gpu'] , 'available_mem' : all_mem - used['mem'] , 'available_cpu' : all_cpu - used['cpu'] , ms_type : current_avl_ms}  
        logger.info("resource :" + str(res))

        logger.info("Resource utilisation Updated")

        return JSONResponse(status_code=200, content=rtn_msg)

    except Exception as e:
        logger.error(e)

        rtn_msg["status"] = "Failure"
        rtn_msg["message"] =  str(e)
        return JSONResponse(status_code=500, content=rtn_msg)


def used_rescource_by_ns(clustername,clusterzone,clusterproject,namespace):
    try:
        used_cpu = 0
        used_mem = 0
        used_gpu = 0

        cmd1 = 'gcloud auth activate-service-account --key-file=' + gke
        cmd2 = 'gcloud container clusters get-credentials '+ clustername + ' --zone ' + clusterzone + ' --project '+ clusterproject
        subprocess.run(cmd1 , shell=True)
        subprocess.run(cmd2 , shell=True)
        config.load_kube_config()

        v1 = client.CoreV1Api()
        res = v1.list_namespace()

        ns_list = []
        for i in res.items:
            ns = i.metadata.name
            ns_list.append(ns)

        print(ns_list)
        print(namespace)

        if namespace not in ns_list:
            logger.info("Creating namaespace")
            v1.create_namespace(client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace)))
            logging.info(f'Created namespace "{namespace}"')

            return {'mem' : used_mem , 'cpu': used_cpu , 'gpu' : used_gpu}


        ret = client.AppsV1Api().list_namespaced_deployment(namespace = namespace)
        
        for deployment in ret.items:
            replicas = deployment.status.replicas
            for container in deployment.spec.template.spec.containers:
                con_used_cpu = container.resources.requests['cpu']
                if con_used_cpu.endswith('m'):
                    con_used_cpu = con_used_cpu.replace('m','')
                    con_used_cpu = int(con_used_cpu)/1000
                else:
                    con_used_cpu = int(con_used_cpu)
                used_cpu += con_used_cpu * replicas
                con_used_mem = container.resources.requests['memory']
                if con_used_mem.endswith('Mi'):
                    con_used_mem = con_used_mem.replace('Mi','')
                    con_used_mem = int(con_used_mem)/1000
                else:
                    con_used_mem = con_used_mem.replace('Gi', '')
                    con_used_mem = int(con_used_mem)
                used_mem += con_used_mem*replicas
                con_used_gpu = 0
                if container.resources.limits:
                    con_used_gpu = int(container.resources.limits['nvidia.com/gpu'])
                used_gpu += con_used_gpu*replicas

        return {'mem' : used_mem , 'cpu': used_cpu , 'gpu' : used_gpu}
    
    except Exception as e:
        logger.error(e)


def get_owner_id(api_key):
    url = "https://dev-microserviceapi-admin.sentient.io/admin/getownerorginfo"

    # Kindly do a utf-8 encode the payload for language other than English.

    headers = {'x-api-key': api_key}

    response = requests.request("GET", url, headers=headers)

    data = json.loads(response.text)
    return data["results"]["owner_id"]

if __name__ == '__main__':
    uvicorn.run("app:app", port=5000, debug = True, reload = True)

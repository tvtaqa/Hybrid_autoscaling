import math
import random
import time
from kubernetes import client, config
from sympy import *
import yaml

_YAML_FILE_NAME = 'arg.yaml'




def decide(loadfromtxt, rpsfromtxt, limitfromtxt, arg):
    p_cpu = arg['p_cpu']
    per_pod_start_time = arg['per_pod_start_time']
    start_time_constraint = arg['start_time_constraint']
    interval = arg['interval']
    service_price = arg['p_service']
    rtt = arg['rtt']


    current_num_pod = 1
    current_rps_pod = -1.0
    current_limit_pod = 1
    current_ws = 0.0
    current_sla_cost = 0
    current_rescource_cost = 0
    current_total_cost = 0
    current_probaility = 0


    recommend_num_pod = 1
    recommend_rps_pod = -1.0
    recommend_limit_pod = 1
    recommend_ws = 0.0
    recommend_sla_cost = 0
    recommend_rescource_cost = 0
    recommend_total_cost = 0
    recommend_probaility = 0

    loadcount = 0
    while True:


        flag = false


        load = loadfromtxt[loadcount]

        if load / (current_num_pod * current_rps_pod) > 1:
            flag = true
        else:

            current_ws, current_probaility = getRTT(load, current_rps_pod, rtt, current_num_pod)
            if current_probaility > 99:
                current_sla_cost = 0
            elif current_probaility > 95:
                current_sla_cost = 0.1 * service_price
            elif current_probaility > 90:
                current_sla_cost = 0.3 * service_price
            else:
                current_sla_cost = service_price
            current_rescource_cost = current_limit_pod * current_num_pod / 1000 * p_cpu
            current_total_cost = current_rescource_cost + current_sla_cost
            if current_ws > rtt:
                flag = true


        totalcost_min = 99999


        historycount = 0
        while historycount < len(rpsfromtxt):
            tmp_limit = limitfromtxt[historycount]
            tmp_rps = rpsfromtxt[historycount]
            tmp_num_pod, tmp_ws, tmp_pro = queue(load, tmp_rps, rtt)
            tmp_sla_cost = -1
            if tmp_pro > 99:
                tmp_sla_cost = 0
            elif tmp_pro > 95:
                tmp_sla_cost = 0.1 * service_price
            elif tmp_pro > 90:
                tmp_sla_cost = 0.3 * service_price
            else:
                tmp_sla_cost = service_price

            tmp_rescource_cost = tmp_num_pod * tmp_limit / 1000 * p_cpu
            tmp_total_cost = tmp_sla_cost + tmp_rescource_cost
            if totalcost_min > tmp_total_cost and tmp_num_pod * per_pod_start_time < interval * start_time_constraint:
                totalcost_min = tmp_total_cost
                recommend_total_cost = tmp_total_cost
                recommend_num_pod = tmp_num_pod
                recommend_limit_pod = tmp_limit
                recommend_rps_pod = tmp_rps
                recommend_ws = tmp_ws
                recommend_sla_cost = tmp_sla_cost
                recommend_rescource_cost = tmp_rescource_cost
                recommend_probaility = tmp_pro
            pass
            historycount = historycount + 1
        pass


        if flag == false:
            percentage = abs(recommend_total_cost - current_total_cost) / current_total_cost
            if percentage > 0.1:
                flag = true
        if flag:

           # execute(recommend_num_pod, recommend_limit_pod, arg)
            print("使用新的推荐方案：")
            print("load:%d" % load)
            print("num_pod :%d" % recommend_num_pod)
            print("limit_pod :%d" % recommend_limit_pod)
            print("rps_pod :%f" % recommend_rps_pod)
            print("ws_pod :%f" % recommend_ws)
            print("ws_pro :%f" % recommend_probaility)
            current_num_pod = recommend_num_pod
            current_rps_pod = recommend_rps_pod
            current_limit_pod = recommend_limit_pod
            current_ws = recommend_ws
            current_probaility = recommend_probaility
            current_rescource_cost = recommend_rescource_cost
            current_sla_cost = recommend_sla_cost
            current_total_cost = recommend_total_cost
        else:
            print("维持当前的方案：")
            print("load:%d" % load)
            print("num_pod :%d" % current_num_pod)
            print("limit_pod :%d" % current_limit_pod)
            print("rps_pod :%f" % current_rps_pod)
            print("ws_pod :%f" % current_ws)
            print("ws_pro :%f" % current_probaility)

        print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        print("*" * 30)

       # time.sleep(interval)
        loadcount = loadcount + 1
        if loadcount >= len(loadfromtxt):
            print("伸缩测试结束")
            break
        pass



def execute(num_pod, limit_pod, arg):
    config.load_kube_config()
    api_instance = client.AppsV1Api()
    deployment = arg['deployment']
    namespace = arg['namespace']
    deployobj = api_instance.read_namespaced_deployment(deployment, namespace)


    recommend_cpu_requests = int(limit_pod)

    recommend_cpu_limits = int(limit_pod)

    recommend_requests = {
        'cpu': str(recommend_cpu_requests) + 'm',

    }
    recommend_limits = {
        'cpu': str(recommend_cpu_limits) + 'm',

    }
    deployobj.spec.template.spec.containers[0].resources.limits.update(recommend_limits)
    deployobj.spec.template.spec.containers[0].resources.requests.update(recommend_requests)
    deployobj.spec.replicas = num_pod
    api_instance.replace_namespaced_deployment(deployment, namespace, deployobj)




def getRTT(load, rps, rtt, c):
    strength = 1.0 * load / (c * rps)
    p0 = 0
    k = 0
    while k <= c - 1:
        p0 += (1.0 / math.factorial(k)) * ((1.0 * load / rps) ** k)
        k = k + 1

    p0 += (1.0 / math.factorial(c)) * (1.0 / (1 - strength)) * ((1.0 * load / rps) ** c)
    p0 = 1 / p0
    lq = ((c * strength) ** c) * strength / (math.factorial(c) * (1 - strength) * (1 - strength)) * p0
    ls = lq + load / rps
    ws = ls / load
    wq = lq / load

    pi_n = ((c * strength) ** c) / math.factorial(c) * p0
    tmp = (math.e ** ((rtt - 1 / rps) * c * rps * (1 - strength))) * (1 - strength)
    probaility = (100 * tmp - 100 * pi_n) / tmp

    return float(ws), probaility





def queue(load, rps, rtt):
    c = 1
    strength = 1.0 * load / (c * rps)
    while True:
        if (strength >= 1):
            c = c + 1
            strength = 1.0 * load / (c * rps)
            continue
        p0 = 0
        k = 0
        while k <= c - 1:
            p0 += (1.0 / math.factorial(k)) * ((1.0 * load / rps) ** k)
            k = k + 1
        p0 += (1.0 / math.factorial(c)) * (1.0 / (1 - strength)) * ((1.0 * load / rps) ** c)
        p0 = 1 / p0
        lq = ((c * strength) ** c) * strength / (math.factorial(c) * (1 - strength) * (1 - strength)) * p0
        ls = lq + load / rps
        ws = ls / load
        wq = lq / load
        if ws < rtt:
            break
        else:
            c = c + 1
            strength = load / (c * rps)

    pi_n = ((c * strength) ** c) / math.factorial(c) * p0
    tmp = (math.e ** ((rtt - 1 / rps) * c * rps * (1 - strength))) * (1 - strength)
    probaility = (100 * tmp - 100 * pi_n) / tmp
    return c, float(ws), probaility


def prepare():
    loadfromtxt = []

    rpsfromtxt = []

    limitfromtxt = []

    file = 'load.txt'
    with open(file, 'r') as file_to_read:
        while True:
            lines = file_to_read.readline()
            if not lines:
                break
                pass
            tmp = int(lines.strip('\n'))
            loadfromtxt.append(tmp)
            pass
    pass
    filename = 'data.txt'
    with open(filename, 'r') as file_to_read:
        while True:
            lines = file_to_read.readline()
            if not lines:
                break
                pass
            tmp_limit, tmp_rps = [float(i) for i in lines.split()]
            rpsfromtxt.append(tmp_rps)
            limitfromtxt.append(tmp_limit)
    pass
    print(loadfromtxt)
    print(limitfromtxt)
    print(rpsfromtxt)
    return loadfromtxt, rpsfromtxt, limitfromtxt


def main():
    with open(_YAML_FILE_NAME) as f:
        arg = yaml.load(f, Loader=yaml.FullLoader)
    loadfromtxt, rpsfromtxt, limitfromtxt = prepare()

    decide(loadfromtxt, rpsfromtxt, limitfromtxt, arg)


if __name__ == '__main__':
    main()
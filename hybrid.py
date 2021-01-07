import math
import random
import time
from kubernetes import client, config
from sympy import *
import yaml

_YAML_FILE_NAME = 'arg.yaml'

'''
负载发生变化时，推荐一个伸缩方案，该方案的目标是总成本最少（资源成本+违约成本）
资源成本的计价方式：参考腾讯云EKS平台 + Kubernetes伸缩机制
违约成本的计价方式：根据所有请求中，能满足SLA协议的请求占比

为了避免频繁地切换伸缩方案，需要加入一定的资源冗余。
所以在使用排队论计算推荐方案时，适当地增加了负载。
比如当前负载为1000，在实际计算的时候，使用了1100来计算推荐方案。该redundancy=1.1

决策：使用推荐方案or维持当前方案
若 （当前方案的总成本-推荐方案的总成本）/ 当前方案的总成本 > thresold，则需要切换到推荐方案（比原方案少了多少的成本，有点矛盾。。）
PS：
'''


def decide(load_txt, rps_txt, limit_txt, arg):
    user_rtt = arg['rtt']
    interval = arg['interval']
    pod_max_limit = arg['pod_max_limit']
    pod_min_limit = arg['pod_min_limit']
    pod_num_max = arg['pod_num_max']
    res_cost_max = interval * math.ceil(pod_max_limit * pod_num_max)
    res_cost_min = interval * math.ceil(pod_min_limit)
    sla_cost_max = 1
    sla_cost_min = 0

    cur_cpu_res, cur_mem_res, cur_num, cur_ws, cur_pro, cur_rps_for_each, cur_sla_cost, cur_res_cost = 1950, 0, 1, 0, 0, 70.1, 0, 0
    loadcount = 0
    while True:
        ischange = false
        # 取当前时刻的负载，从文件中读取
        load = load_txt[loadcount]

        # 如果出现无限排队现象，则违约成本就是1
        if load / (cur_num * cur_rps_for_each) >= 1:
            cur_sla_cost = 1
        elif load / (cur_num * cur_rps_for_each) < 1:
            # 更新值，如果在当前时刻的负载下，继续使用该方案的ws和pro为多少
            cur_ws, cur_pro = getRTT(load, cur_rps_for_each, user_rtt, cur_num, 1)
            cur_sla_cost = get_sla_cost(arg, cur_pro)

        # 计算维持当前方案的资源成本
        cur_res_cost = math.ceil(cur_cpu_res * cur_num / 1000) * arg['p_cpu'] * arg['interval']

        # 将旧方面的资源成本和违约成本都归一化
        cur_normal_res_cost = (res_cost_max - cur_res_cost) / (res_cost_max - res_cost_min)
        cur_normal_sla_cost = (sla_cost_max - cur_sla_cost) / (sla_cost_max - sla_cost_min)
        cur_score = cur_normal_res_cost + cur_normal_sla_cost

        opt_num, opt_cpu_res, opt_rps, opt_ws, opt_pro, opt_res_cost, opt_sla_cost, opt_score \
            = getOptimalPlan(load, rps_txt, limit_txt, arg, cur_num, cur_cpu_res)

        # 将日志写到文件中
        outputlog(loadcount, load, opt_score, cur_score, opt_rps, cur_rps_for_each,
                  opt_num, cur_num, opt_cpu_res, cur_cpu_res, opt_ws, cur_ws, opt_pro, cur_pro)

        # 决策，是否使用最新的推荐方案
        if (opt_score - cur_score) / cur_score > arg['thresold']:
            cur_cpu_res, cur_num, cur_ws, cur_pro, cur_rps_for_each, cur_res_cost, cur_sla_cost = \
                opt_cpu_res, opt_num, opt_ws, opt_pro, opt_rps, opt_res_cost, opt_sla_cost
            ischange = true
            # 执行伸缩方案
            # execute(cur_num, cur_cpu_res, arg)

        outputre(ischange, load, loadcount, cur_num, cur_cpu_res, cur_rps_for_each, cur_ws, cur_pro, cur_res_cost,
                 cur_sla_cost)

        # time.sleep(arg['interval'])
        loadcount = loadcount + 1
        if loadcount >= len(load_txt):
            print("伸缩测试结束\n")
            break
        pass


def outputre(ischange, load, loadcount, cur_num, cur_cpu_res, cur_rps_for_each, cur_ws, cur_pro, opt_res_cost,
             opt_sla_cost):
    print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
    print("current index: %d " % loadcount)
    print("load: %d" % load)
    print("pod_num: %d\npod_res: %d\npod_total_res: %d " % (cur_num, cur_cpu_res, cur_cpu_res * cur_num))
    print("pod_rps: %f\npod_total_rps: %d " % (cur_rps_for_each, cur_rps_for_each * cur_num))
    print("svc_ws: %f\nsvc_pro: %f" % (cur_ws, cur_pro))
    print("res_cost: %f\nsla_cost: %f" % (opt_res_cost, opt_sla_cost))
    print("*" * 40)

    f = open('hybrid_result.txt', 'a')
    f.write(time.strftime("\n%Y-%m-%d %H:%M:%S\n", time.localtime()))
    f.write("current index: %d \n" % loadcount)
    f.write("load: %d\n" % load)
    f.write("pod_num: %d\npod_res: %d\npod_total_res: %d\n" % (cur_num, cur_cpu_res, cur_cpu_res * cur_num))
    f.write("pod_rps: %f\npod_total_rps: %d\n" % (cur_rps_for_each, cur_rps_for_each * cur_num))
    f.write("svc_ws: %f\nsvc_pro: %f\n" % (cur_ws, cur_pro))
    f.write("res_cost: %f\nsla_cost: %f\n" % (opt_res_cost, opt_sla_cost))
    f.write("*" * 30)
    f.close()


def outputlog(loadcount, load, opt_score, old_score, opt_rps, cur_rps_for_each,
              opt_num, cur_num, opt_cpu_res, cur_cpu_res, opt_ws, cur_ws, opt_pro, cur_pro):
    # print("当前的load: %d" % load)
    # print("推荐方案的得分：%f vs 旧方案的得分：%f" % (opt_score, old_score))
    # print("推荐方案的的rps: %f vs 旧方案的rps：%f" % (opt_rps, cur_rps_for_each))
    # print("推荐方案的的num: %d vs 旧方案的num：%d" % (opt_num, cur_num))
    # print("推荐方案的CPU资源量: %d vs 旧方案的CPU资源量：%d" % (opt_num * opt_cpu_res, cur_num * cur_cpu_res))
    # print("推荐方案的的res: %d vs 旧方案的res: %d" % (opt_cpu_res, cur_cpu_res))
    # print("推荐方案的的ws: %f vs 旧方案的ws：%f" % (opt_ws, cur_ws))
    # print("推荐方案的的概率: %f vs 旧方案的的概率: %f" % (opt_pro, cur_pro))

    f = open('hybrid_log.txt', 'a')
    f.write(time.strftime("\n%Y-%m-%d %H:%M:%S\n", time.localtime()))
    f.write("当前索引: %d\n" % loadcount)
    f.write("当前的load: %d\n" % load)
    f.write("推荐方案的得分：%f vs 旧方案的得分：%f\n" % (opt_score, old_score))
    f.write("推荐方案的的rps: %f vs 旧方案的rps：%f\n" % (opt_rps, cur_rps_for_each))
    f.write("推荐方案的的num: %d vs 旧方案的num：%d\n" % (opt_num, cur_num))
    f.write("推荐方案的CPU资源量: %d vs 旧方案的CPU资源量：%d\n" % (opt_num * opt_cpu_res, cur_num * cur_cpu_res))
    f.write("推荐方案的的res: %d vs 旧方案的res: %d\n" % (opt_cpu_res, cur_cpu_res))
    f.write("推荐方案的的ws: %f vs 旧方案的ws：%f\n" % (opt_ws, cur_ws))
    f.write("推荐方案的的概率: %f vs 旧方案的的概率: %f\n" % (opt_pro, cur_pro))
    f.write("*" * 50)

    f.close()


def get_sla_cost(arg, pro):
    sla_1st_pro = arg['sla_level_one_pro']
    sla_1st_punish = arg['sla_level_one_punishment']
    sla_2st_pro = arg['sla_level_two_pro']
    sla_2st_punish = arg['sla_level_two_punishment']
    sla_3st_pro = arg['sla_level_three_pro']
    sla_3st_punish = arg['sla_level_three_punishment']
    sla_4st_pro = arg['sla_level_four_pro']
    sla_4st_punish = arg['sla_level_four_punishment']
    sla_cost = 0
    if pro > sla_1st_pro:
        sla_cost = sla_1st_punish
    elif pro > sla_2st_pro:
        sla_cost = sla_2st_punish
    elif pro > sla_3st_pro:
        sla_cost = sla_3st_punish
    elif pro >= sla_4st_pro:
        sla_cost = sla_4st_punish
    return sla_cost


'''
遍历所有的实例模版，得到最优的推荐方案
目标函数：min(资源成本+违约成本)
'''


def getOptimalPlan(load, rps_txt, limit_txt, arg, old_n, old_cpu):
    user_rtt = arg['rtt']
    ms = arg['ms']
    mu = arg['mu']
    p_cpu = arg['p_cpu']
    interval = arg['interval']
    t1 = arg['per_pod_start_time']
    pod_max_limit = arg['pod_max_limit']
    pod_min_limit = arg['pod_min_limit']
    pod_num_max = arg['pod_num_max']
    redundancy = arg['redundancy']

    # 提前定好资源成本、违约成本的最大值
    res_cost_max = interval * math.ceil(pod_max_limit * pod_num_max)
    res_cost_min = interval * math.ceil(pod_min_limit)
    sla_cost_max = 1
    sla_cost_min = 0
    max_score = 0

    optimal_num, optimal_pod_res, optimal_pod_rps, optimal_ws, optimal_pro, optimal_res_cost, optimal_sla_cost = 0, 0, 0, 0, 0, 0, 0

    historycount = 0

    # 遍历当前所有的实例模版，选择最优的方案
    while historycount < len(rps_txt):
        new_pod_cpu = limit_txt[historycount]
        new_rps = rps_txt[historycount]

        # 对该实例模版进行求解，从1->pod_num_max ,依次求得其资源成本与违约成本。所以应该是一个循环
        pod_num_count = 1
        while pod_num_count < pod_num_max:
            new_ws, new_proportion = getRTT(load, new_rps, user_rtt, pod_num_count, redundancy)

            # 方案启动后，总的资源量(cpu和内存) 目前只考虑CPU
            new_total_cpu_res = pod_num_count * new_pod_cpu
            new_res_cost = 0

            # 计算资源成本,分水平伸缩和组合式伸缩
            if new_pod_cpu == old_cpu:
                # CPU的资源成本
                new_res_cost = math.ceil(new_total_cpu_res / 1000) * p_cpu * interval
                # Mem的资源成本
            elif new_pod_cpu != old_cpu:
                # 旧实例的初始个数
                old_initial_n = math.ceil(pod_num_count * (1 - mu))
                msn = math.ceil(pod_num_count * (1 + ms))
                parn = msn - old_initial_n
                j = parn
                while j <= pod_num_count:
                    new_res_cost = math.ceil((j * new_pod_cpu + (msn - j) * old_cpu) / 1000) * t1 * p_cpu
                    j = j + 1
                j = 1
                while j <= msn - pod_num_count - 1:
                    new_res_cost += math.ceil((pod_num_count * new_pod_cpu + j * old_cpu) / 1000) * t1 * p_cpu
                    j = j + 1
                new_res_cost += (interval - (old_initial_n * t1)) * math.ceil(new_total_cpu_res / 1000) * p_cpu

            # 计算违约成本
            new_sla_cost = get_sla_cost(arg, new_proportion)

            # 进行归一化，如果该得分更高，则更新
            tmp_res_cost = (res_cost_max - new_res_cost) / (res_cost_max - res_cost_min)
            tmp_sla_cost = (sla_cost_max - new_sla_cost) / (sla_cost_max - sla_cost_min)
            if tmp_res_cost + tmp_sla_cost > max_score:
                max_score = tmp_res_cost + tmp_sla_cost
                # 记录必要的信息（包括实例个数，资源量，ws，满足SLA的占比等）
                optimal_num, optimal_pod_res, optimal_pod_rps, optimal_ws, optimal_pro, optimal_res_cost, optimal_sla_cost \
                    = pod_num_count, new_pod_cpu, new_rps, new_ws, new_proportion, new_res_cost, new_sla_cost

            pod_num_count = pod_num_count + 1
        pass
        historycount = historycount + 1
    pass
    return optimal_num, optimal_pod_res, optimal_pod_rps, optimal_ws, optimal_pro, optimal_res_cost, optimal_sla_cost, max_score


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


def getRTT(load, rps, rtt, c, redundancy):
    load = load * redundancy
    strength = 1.0 * load / (c * rps)
    if strength >= 1:
        return -1, 0
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


def queue(load, rps, rtt, redundancy):
    load = math.ceil(load * redundancy)
    c = 1
    strength = 1.0 * load / (c * rps)
    while True:
        if strength >= 1:
            c = c + 1
            strength = 1.0 * load / (c * rps)
            continue
        if c > 30:
            return 10000, -1, 0
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
    load_txt = []

    rps_txt = []

    limit_txt = []

    file = 'load.txt'
    with open(file, 'r') as file_to_read:
        while True:
            lines = file_to_read.readline()
            if not lines:
                break
                pass
            tmp = int(lines.strip('\n'))
            load_txt.append(tmp)
            pass
    pass
    filename = 'data.txt'
    with open(filename, 'r') as file_to_read:
        while True:
            lines = file_to_read.readline()
            if not lines:
                break
                pass
            cursorPerPodRescource, cursorRps = [float(i) for i in lines.split()]
            rps_txt.append(cursorRps)
            limit_txt.append(cursorPerPodRescource)
    pass
    print(load_txt)
    print(limit_txt)
    print(rps_txt)
    return load_txt, rps_txt, limit_txt


def main():
    with open(_YAML_FILE_NAME) as f:
        arg = yaml.load(f, Loader=yaml.FullLoader)
    load_txt, rps_txt, limit_txt = prepare()

    decide(load_txt, rps_txt, limit_txt, arg)
    f = open('hybrid_log.txt', 'a')
    f.write("\nend of the test\n\n\n\n\n")
    f.close()
    f = open('hybrid_result.txt', 'a')
    f.write("\nend of the test\n\n\n\n\n")
    f.close()


if __name__ == '__main__':
    main()

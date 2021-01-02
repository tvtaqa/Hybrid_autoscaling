import math
import random
import time
from kubernetes import client, config
from sympy import *
import yaml

_YAML_FILE_NAME = 'arg.yaml'

'''
以资源量最少为目标
'''


def decide(load_txt, rps_txt, limit_txt, arg):
    user_rtt = arg['rtt']
    cur_cpu_res, cur_mem_res, cur_num, cur_ws, cur_pro, cur_rps_for_each = 0, 0, 0, 0, 0, 0
    loadcount = 0
    while True:
        flag = false
        # 取当前时刻的负载，从文件中读取
        load = load_txt[loadcount]

        # 出现无限排队/逗留时间超过用户规定的时间，使用推荐方案
        if loadcount > 1 and load / (cur_num * cur_rps_for_each) >= 1:
            flag = true
        elif loadcount > 1 and load / (cur_num * cur_rps_for_each) < 1:
            # 更新值，如果在当前时刻的负载下，继续使用该方案的ws和pro为多少
            cur_ws, cur_pro = getRTT(load, cur_rps_for_each, user_rtt, cur_num)
            if cur_ws > user_rtt:
                flag = true

        opt_cpu_res, opt_num, opt_ws, opt_pro, opt_rps = getOptimalPlan(load, rps_txt, limit_txt, arg,
                                                                        cur_num, cur_cpu_res, cur_mem_res)
        cur_cpu_res, cur_num, cur_ws, cur_pro, cur_rps_for_each = opt_cpu_res, opt_num, opt_ws, opt_pro, opt_rps

        print("当前的load: %d" % load)
        print("推荐方案的的rps: %f" % opt_rps)
        print("推荐方案的的num: %d" % opt_num)
        print("推荐方案的的res: %d" % opt_cpu_res)
        print("推荐方案的的ws: %f" % opt_ws)
        print("推荐方案的的概率: %f" % opt_pro)

        # 决策：是否使用最新的推荐的方案

        print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        print("*" * 30)

        # time.sleep(interval)
        loadcount = loadcount + 1
        if loadcount >= len(load_txt):
            print("伸缩测试结束")
            break
        pass


'''
遍历所有的实例模版，得到最优的推荐方案
目标函数：min(资源成本+违约成本)
'''


def getOptimalPlan(load, rps_txt, limit_txt, arg, old_n, old_cpu, old_mem):
    user_rtt = arg['rtt']
    ms = arg['ms']
    mu = arg['mu']
    p_cpu = arg['p_cpu']
    interval = arg['interval']
    t1 = arg['per_pod_start_time']
    sla_1st_pro = arg['sla_level_one_pro']
    sla_1st_punish = arg['sla_level_one_punishment']
    sla_2st_pro = arg['sla_level_two_pro']
    sla_2st_punish = arg['sla_level_two_punishment']
    sla_3st_pro = arg['sla_level_three_pro']
    sla_3st_punish = arg['sla_level_three_punishment']
    sla_4st_pro = arg['sla_level_four_pro']
    sla_4st_punish = arg['sla_level_four_punishment']

    # 内存资源暂时不考虑
    pod_mem_list = []

    pod_cpu_list = []
    pod_num_list = []
    proportion_list = []
    sla_cost_list = []
    res_cost_list = []
    rps_list = []
    ws_list = []

    res_cost_max = -1
    res_cost_min = 99999
    sla_cost_max = -1
    sla_cost_min = 99999

    historycount = 0
    # 遍历当前所有的实例模版，选择最优的方案
    while historycount < len(rps_txt):
        new_pod_cpu = limit_txt[historycount]
        new_rps = rps_txt[historycount]

        # 对该实例模版进行求解，得到最少的实例个数，以及该方案下的逗留时间和小于user_rtt的占比
        new_num, new_ws, new_proportion = queue(load, new_rps, user_rtt)

        # 方案启动后，总的资源量(cpu和内存) 目前只考虑CPU
        new_total_cpu_res = new_num * new_pod_cpu

        new_res_cost = 0
        # 计算资源成本,分水平伸缩和组合式伸缩
        if new_pod_cpu == old_cpu:
            # CPU的资源成本
            new_res_cost = math.ceil(new_total_cpu_res / 1000) * p_cpu * interval
            # Mem的资源成本
        else:
            old_initial_n = math.ceil(new_num * (1 - mu))
            msn = math.ceil(new_num * (1 + ms))
            parn = msn - old_initial_n
            j = parn
            while j <= new_num:
                new_res_cost = math.ceil((j * new_pod_cpu + (msn - j) * old_cpu)/1000) * t1 * p_cpu
                j = j + 1
            j = 1
            while j <= msn - new_num - 1:
                new_res_cost += math.ceil((new_num * new_pod_cpu + j * old_cpu)/1000) * t1 * p_cpu
                j = j + 1
            new_res_cost += (interval - (old_initial_n * t1)) * math.ceil(new_num * new_pod_cpu / 1000) * p_cpu

        new_sla_cost = 0
        # 计算违约成本
        if new_proportion > sla_1st_pro:
            new_sla_cost = sla_1st_punish
        elif new_proportion > sla_2st_pro:
            new_sla_cost = sla_2st_punish
        elif new_proportion > sla_3st_pro:
            new_sla_cost = sla_3st_punish
        elif new_proportion > sla_4st_pro:
            new_sla_cost = sla_4st_punish

        # 记录资源成本和违约成本的 最小最大值 方便后序的归一化
        if new_res_cost > res_cost_max:
            res_cost_max = new_res_cost
        elif new_res_cost < res_cost_min:
            res_cost_min = new_res_cost
        if new_sla_cost > sla_cost_max:
            sla_cost_max = new_sla_cost
        elif new_sla_cost < sla_cost_min:
            sla_cost_min = new_sla_cost

        # 将必要的信息存到数组中
        pod_cpu_list.append(new_pod_cpu)
        pod_num_list.append(new_num)
        proportion_list.append(new_proportion)
        rps_list.append(new_rps)
        ws_list.append(new_ws)
        res_cost_list.append(new_res_cost)
        sla_cost_list.append(new_sla_cost)

        historycount = historycount + 1
    pass
    # 进行max-min归一化
    index = 0
    optimalScore = -1
    optimalIndex = 0
    while index < len(limit_txt):
        normal_res_cost = (res_cost_max - res_cost_list[index]) / (res_cost_max - res_cost_min)
        if (sla_cost_max - sla_cost_min) == 0:
            normal_sla_cost = 0
        else:
            normal_sla_cost = (sla_cost_max - sla_cost_list[index]) / (sla_cost_max - sla_cost_min)
        tmptotalscore = normal_res_cost + normal_sla_cost
        if tmptotalscore > optimalScore:
            optimalIndex = index
            optimalScore = tmptotalscore
        index = index + 1
    pass

    # 下标为optimalIndex的，即最优的方案
    return pod_cpu_list[optimalIndex], pod_num_list[optimalIndex] \
        , ws_list[optimalIndex], proportion_list[optimalIndex], rps_list[optimalIndex]


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


if __name__ == '__main__':
    main()

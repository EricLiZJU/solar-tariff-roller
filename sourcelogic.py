import openpyxl
import numpy_financial as npf
import os

# ============== 配置区 ==============
FILE_PATH = r'/Users/lihongyang/Desktop/【测算表】中财管道.xlsx'
TARGET_IRR = 0.09  # 目标IRR（所得税前），如需9%则填0.09
# ====================================


def load_data(filepath):
    """加载Excel数据"""
    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb['项目基础数据']
    ws2 = wb['月滚动现金流量表']
    return wb, ws, ws2


def get_parameters(ws, ws2):
    """从项目基础数据获取参数"""
    O_old = ws['D26'].value  # 当前自用电折后价
    grid_price = ws['D23'].value  # 上网电价
    self_use_ratio = ws['C15'].value  # 自用消纳率
    investment = ws2['F6'].value  # 总投资
    om_annual = ws['G10'].value  # 年运维费
    return O_old, grid_price, self_use_ratio, investment, om_annual


def get_p_m_values(ws):
    """获取自用电费(P)和上网电费(M) - years 1-25"""
    p_values = []
    m_values = []
    for r in range(63, 88):  # rows 63-87 = years 1-25
        p = ws.cell(r, 16).value  # P column
        m = ws.cell(r, 13).value  # M column
        if isinstance(p, (int, float)) and isinstance(m, (int, float)):
            p_values.append(p)
            m_values.append(m)
    return p_values, m_values


def get_baseline_c(ws2):
    """获取月度含税收入基准值（硬编码部分：C7-C50）"""
    baseline_c = []
    for r in range(7, 51):  # rows 7-50 = months 1-44
        c = ws2.cell(r, 3).value
        baseline_c.append(c if c else 0)
    return baseline_c


def get_baseline_m(ws2):
    """获取月度现金流基准值"""
    baseline_m = []
    for r in range(6, 307):
        m = ws2.cell(r, 13).value
        baseline_m.append(m if m else 0)
    return baseline_m


def compute_irr(O_new, O_old, baseline_c, p_values, m_values,
                self_use_ratio, grid_price, investment, om_annual):
    """
    根据新电价计算IRR
    
    C列结构：
    - Months 1-44 (C7-C50): 硬编码，固定（按比例缩放）
    - Months 45-300 (C51-C306): 公式引用Q列，随电价变化
    
    C51-C54 = Q66/12 (year 1)
    C55-C66 = Q67/12 (year 2)
    C67-C78 = Q68/12 (year 3)
    ...
    """
    # 计算混合价格比例
    k_old = self_use_ratio * O_old + (1 - self_use_ratio) * grid_price
    k_new = self_use_ratio * O_new + (1 - self_use_ratio) * grid_price
    ratio = k_new / k_old
    
    # 构建月度C值
    monthly_c = []
    
    # Months 1-44: 硬编码值按比例调整
    for c in baseline_c:
        monthly_c.append(c * ratio)
    
    # 计算新的Q值
    q_new = []
    for i in range(25):
        p_new = p_values[i] * (O_new / O_old)
        q_new.append(m_values[i] + p_new)
    
    # Months 45+: 从Q列计算
    # C51-C54 (4 months): Q66/12 (year 1, index 0)
    for _ in range(4):
        monthly_c.append(q_new[0] / 12)
    
    # C55-C66 (12 months): Q67/12 (year 2, index 1)
    for _ in range(12):
        monthly_c.append(q_new[1] / 12)
    
    # C67-C78 (12 months): Q68/12 (year 3, index 2)
    for _ in range(12):
        monthly_c.append(q_new[2] / 12)
    
    # Years 4-25 (indices 3-24)
    for year_idx in range(3, 25):
        for _ in range(12):
            monthly_c.append(q_new[year_idx] / 12)
    
    monthly_c = monthly_c[:300]  # 取前300个月
    
    # 计算现金流
    cashflows = []
    k_carry = 0  # 增值税结转
    insurance = investment * 0.001
    om_half = om_annual / 2
    
    # Month 0: 初始投资
    I0 = round((investment * 0.7 / 1.13 * 0.13 + investment * 0.3 / 1.09 * 0.09), 2)
    cashflows.append(-investment)
    k_carry = -I0
    
    # Months 1-300
    for m in range(300):
        month_num = m + 1
        c = monthly_c[m]
        
        # 成本费用
        g_m = insurance if (month_num % 12 == 1) else 0
        h_m = om_half if (month_num % 6 == 1) else 0
        i_total = g_m + h_m
        
        # 进项税金
        j_m = round(i_total / 1.06 * 0.06, 2) if i_total > 0 else 0
        
        # 销项税金
        d_m = round(c / 1.13, 2)
        e_m = round(d_m * 0.13, 2)
        
        # 应缴增值税
        k_m = e_m - j_m + k_carry
        k_carry = min(k_m, 0) if k_m < 0 else 0
        
        # 教育费及附加
        l_m = round(k_m * 0.12, 2) if k_m > 0 else 0
        
        # 当期现金流
        m_cf = c - i_total - (k_m if k_m > 0 else 0) - l_m
        cashflows.append(m_cf)
    
    return npf.irr(cashflows) * 12  # 年化IRR


def binary_search(O_old, baseline_c, p_values, m_values,
                  self_use_ratio, grid_price, investment, om_annual,
                  target_irr, lo=0.3, hi=0.9):
    """二分法查找目标电价"""
    for _ in range(100):
        mid = (lo + hi) / 2
        irr = compute_irr(mid, O_old, baseline_c, p_values, m_values,
                         self_use_ratio, grid_price, investment, om_annual)
        if irr > target_irr:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def main():
    print("=" * 50)
    print("中财管道光伏项目IRR反推电价计算")
    print("=" * 50)
    
    if not os.path.exists(FILE_PATH):
        print(f"错误：找不到文件 {FILE_PATH}")
        return
    
    # 加载数据
    print(f"\n正在读取: {os.path.basename(FILE_PATH)}")
    wb, ws, ws2 = load_data(FILE_PATH)
    
    # 获取参数
    O_old, grid_price, self_use_ratio, investment, om_annual = get_parameters(ws, ws2)
    p_values, m_values = get_p_m_values(ws)
    baseline_c = get_baseline_c(ws2)
    baseline_m = get_baseline_m(ws2)
    
    print(f"\n模型参数:")
    print(f"  当前电价 O = {O_old:.4f} 元/kWh")
    print(f"  上网电价 = {grid_price:.4f} 元/kWh")
    print(f"  自用消纳率 = {self_use_ratio:.0%}")
    print(f"  总投资 = {investment:.2f} 万元")
    print(f"  年运维费 = {om_annual:.2f} 万元")
    print(f"  硬编码月份: 1-44 (C7-C50)")
    print(f"  公式月份: 45-300 (C51-C306)")
    print(f"  目标 IRR = {TARGET_IRR:.0%}")
    
    # 验证当前IRR
    irr_current = npf.irr(baseline_m) * 12
    print(f"  当前 IRR = {irr_current:.4%}")
    
    # 二分搜索
    print(f"\n正在计算...")
    O_result = binary_search(O_old, baseline_c, p_values, m_values,
                             self_use_ratio, grid_price, investment, om_annual,
                             TARGET_IRR)
    
    # 验证结果
    irr_result = compute_irr(O_result, O_old, baseline_c, p_values, m_values,
                           self_use_ratio, grid_price, investment, om_annual)
    
    print(f"\n" + "=" * 50)
    print(f"计算结果:")
    print(f"  目标电价 O66-O87 = {O_result:.4f} 元/kWh")
    print(f"  对应 D24 = {O_result / 0.85:.4f} 元/kWh")
    print(f"  验证 IRR = {irr_result:.4%}")
    print(f"=" * 50)
    
    print(f"\n操作建议:")
    print(f"  在项目基础数据表的 O66-O87 单元格输入 {O_result:.4f}")
    print(f"  预计 IRR 将达到约 {irr_result:.2%}（满足 ≥9% 的要求）")


if __name__ == "__main__":
    main()
import streamlit as st
import pandas as pd
import time

# -----------------------------------------------------------------------------
# 0. 页面基本配置
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="香港特色咖啡店选址与租金压力分析系统",
    page_icon="☕",
    layout="wide"
)

st.title("☕ 香港特色咖啡店选址与商圈租金分析系统")
st.caption("帮助餐饮创业者评估商圈潜力、探索顾客口碑偏好与查找放租商铺")

# -----------------------------------------------------------------------------
# 1. 伪数据定义 (Mock Data - 后续由成员 1, 2, 3 的真实函数替换)
# -----------------------------------------------------------------------------
def get_mock_business_districts():
    """获取可选商圈列表"""
    return ["上环 (Sheung Wan)", "深水埗 (Sham Shui Po)", "西营盘 (Sai Ying Pun)", "尖沙咀 (Tsim Sha Tsui)"]

def get_mock_district_data(district_name):
    """模拟根据商圈获取的核心指标、评论大字图关键词及放租商铺"""
    # 模拟数据
    summary = {
        "avg_spend": 78.5,           # 平均人均消费
        "avg_sqft_rent": 115.0,      # 平均尺租
        "rent_pressure_index": 7.2,  # 租金压力指数 (1-10)
        "total_cafes": 42
    }
    
    # 评论关键词及关联的原句
    keywords_with_reviews = {
        "☕ 咖啡出品优质": [
            "Hand drip 选项很多，单品豆风味突出，很有惊喜！",
            "咖啡品质极高，拉花也很漂亮，值得回头。"
        ],
        "📸 装潢适合打卡": [
            "工业风装修很出片，采光非常好，周末很多人排队拍照。",
            "店铺设计有特色，氛围感拉满。"
        ],
        "💸 价格偏贵": [
            "一杯 Flat White 要 $55，性价比不算高。",
            "食物分量偏小，单价稍贵。"
        ],
        "🤫 环境安静": [
            "平时去人不算多，很适合带电脑工作一个下午。",
            "音乐播放得恰到好处，不吵闹。"
        ]
    }
    
    # 模拟放租商铺列表
    rental_shops = pd.DataFrame([
        {"商铺名称": "上环皇后大道中地下A铺", "面积(尺)": 450, "月租(HKD)": 52000, "尺租(HKD)": 115.5, "适合度": "高 (适合精品小店)"},
        {"商铺名称": "上环毕街拐角地铺", "面积(尺)": 600, "月租(HKD)": 78000, "尺租(HKD)": 130.0, "适合度": "中 (适合中型Cafe)"},
        {"商铺名称": "上环苏豪区巷内铺", "面积(尺)": 320, "月租(HKD)": 35000, "尺租(HKD)": 109.3, "适合度": "高 (低成本起步)"},
        {"商铺名称": "上环德辅道中大路铺", "面积(尺)": 900, "月租(HKD)": 135000, "尺租(HKD)": 150.0, "适合度": "低 (租金压力大)"},
    ])
    
    return summary, keywords_with_reviews, rental_shops

# -----------------------------------------------------------------------------
# 2. 侧边栏：交互控制区
# -----------------------------------------------------------------------------
st.sidebar.header("🎯 选择与筛选栏")

# 下拉菜单：选择商圈
selected_district = st.sidebar.selectbox(
    "请选择目标商圈：",
    options=get_mock_business_districts()
)

# 动态加载动画模拟（模拟后端爬取/处理过程）
fetch_button = st.sidebar.button("🔄 实时同步/更新数据", use_container_width=True)
if fetch_button:
    with st.spinner(f"正在实时获取并分析【{selected_district}】的最新数据..."):
        time.sleep(1.5)  # 模拟延迟
    st.sidebar.success("数据更新成功！")

st.sidebar.divider()
st.sidebar.subheader("🏪 放租商铺筛选")
price_range = st.sidebar.slider("月租预算范围 (HKD)：", 20000, 150000, (30000, 80000), step=5000)
min_size = st.sidebar.number_input("最小面积需求 (尺)：", min_value=100, max_value=2000, value=300)

# -----------------------------------------------------------------------------
# 3. 主界面布局
# -----------------------------------------------------------------------------
# 获取当前商圈数据 (伪数据)
summary, keywords_map, rental_df = get_mock_district_data(selected_district)

st.header(f"📍 当前分析商圈：{selected_district}")

# --- 模块一：核心经济学与商业指标卡片 ---
st.subheader("📊 核心商业指标大盘")
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("平均人均消费", f"HKD ${summary['avg_spend']}")
with col2:
    st.metric("平均尺租", f"HKD ${summary['avg_sqft_rent']}/尺")
with col3:
    st.metric("租金压力指数", f"{summary['rent_pressure_index']} / 10", delta="中等偏高", delta_color="inverse")
with col4:
    st.metric("区域特色咖啡店数", f"{summary['total_cafes']} 间")

st.divider()

# --- 模块二：评论大字图/关键词与弹窗交互 ---
st.subheader("💬 顾客口碑关键词分析（点击关键词查看原评论）")
st.write("以下为大模型（LLM）提取的近期顾客核心关注标签：")

# 使用按钮排布模拟大字图
kw_cols = st.columns(len(keywords_map))
for i, (kw, reviews) in enumerate(keywords_map.items()):
    with kw_cols[i % len(keywords_map)]:
        # 点击按钮触发对话框/弹窗展示原评论
        if st.button(f"🏷️ {kw}", key=f"kw_btn_{i}", use_container_width=True):
            @st.dialog(f"关于【{kw}】的顾客原评论及摘要")
            def show_reviews_dialog():
                st.write("**🤖 LLM 一句话总结：** 该商圈顾客对该维度的讨论非常集中。")
                st.divider()
                st.write("**📜 代表性评价原文：**")
                for r in reviews:
                    st.info(f"“ {r} ”")
            show_reviews_dialog()

st.divider()

# --- 模块三：可筛选的实时放租商铺列表 ---
st.subheader("🏢 该商圈实时放租商铺推荐")

# 应用侧边栏的过滤条件
filtered_df = rental_df[
    (rental_df["月租(HKD)"] >= price_range[0]) &
    (rental_df["月租(HKD)"] <= price_range[1]) &
    (rental_df["面积(尺)"] >= min_size)
]

st.dataframe(
    filtered_df,
    use_container_width=True,
    hide_index=True
)

st.caption(f"共找到 {len(filtered_df)} 间符合条件的放租商铺。")
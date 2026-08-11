#!/usr/bin/env python
# coding: utf-8

# In[1]:


from jqdata import *
import pandas as pd
import ipywidgets as widgets
from IPython.display import display, clear_output, HTML

display(HTML("<style>.container { width:100% !important; }</style>"))
javascript_functions = {False: "hide()", True: "show()"}
button_descriptions  = {False: "Show code", True: "Hide code"}

def toggle_code(state):
    output_string = "<script>$(\"div.input\").{}</script>"
    output_args   = (javascript_functions[state],)
    output        = output_string.format(*output_args)
    display(HTML(output))
    
def button_action(value):
    state = value.new
    toggle_code(state)
    value.owner.description = button_descriptions[state]
    
state = False
toggle_code(state)
button = widgets.ToggleButton(state, description = button_descriptions[state])
button.observe(button_action, "value")
display(button)


# In[2]:


def forcast(date=datetime.datetime.today()):
    '''
    获取业绩预告，预告截止日期大于date，返回一个df
    '''
    
    df = finance.run_query(query(        
        finance.STK_FIN_FORCAST.code.label('股票代码'),
        finance.STK_FIN_FORCAST.pub_date.label('发布日期'),               
        finance.STK_FIN_FORCAST.end_date.label('报告截止'),
        finance.STK_FIN_FORCAST.report_type.label('报告期'),
        finance.STK_FIN_FORCAST.type.label('预告类型'),  

        finance.STK_FIN_FORCAST.content.label('概述'),         
        finance.STK_FIN_FORCAST.profit_ratio_min.label('同比Min%'), 
        finance.STK_FIN_FORCAST.profit_ratio_max.label('同比Max%'), 
        finance.STK_FIN_FORCAST.profit_min.label('净利润Min'),
        finance.STK_FIN_FORCAST.profit_max.label('净利润Max'), 
        finance.STK_FIN_FORCAST.profit_last.label('去年同期'), 
    ).filter(
        finance.STK_FIN_FORCAST.end_date.label('报告截止') >= date))
    
    names=[]
    for i in list(df['股票代码']):
        names.append(get_security_info(i).display_name)        
    df['股票名称']=names
    
    df = df.sort_values(axis=0,by=['报告截止','发布日期','预告类型','同比Min%',],ascending=[False,False,True,False],inplace=False)
    
    df=df[['股票代码','股票名称','发布日期','报告截止','报告期','预告类型','同比Min%','同比Max%','概述','净利润Min','净利润Max','去年同期']]
    
    df = df.reset_index(drop=True)
    
    return df


# In[3]:


def get_profit(code,date=datetime.datetime.today()):
    '''
    获得过去几年和最近一期业绩预告净利润，返回df
    code:股票代码
    date：日期

    '''
    year=datetime.datetime.now().year
    years_list=[]
    for i in range(0,16):
        years_list.append(str(year - i//4) + 'q' + str(4-i%4))

    years=[]    
    for i in range(0,10):
        years.append(str(year - i)) #六位数股票代码

    period = years

    q1 = query(
        balance.statDate.label('期末'),
        income.np_parent_company_owners.label('净利润'), 
        indicator.inc_net_profit_to_shareholders_year_on_year.label('同比%'), 
    ).filter(valuation.code == code).order_by(balance.statDate.label('期末').asc(),)

    rets = [get_fundamentals(q1, statDate=i) for i in period]
    df1 = pd.concat(rets).set_index('期末')
    df_list=[]
    df_list.append(df1)
    df1 = pd.concat(df_list,axis=0)
    df1.fillna(0, inplace=True)  
    df1=df1.sort_index()
    
    q0=query(
        finance.STK_FIN_FORCAST.end_date.label('期末'),
        finance.STK_FIN_FORCAST.profit_min.label('净利润'),
        finance.STK_FIN_FORCAST.profit_ratio_min.label('同比%'),
    ).filter(
        finance.STK_FIN_FORCAST.code==code,finance.STK_FIN_FORCAST.end_date>= date
    ).order_by(finance.STK_FIN_FORCAST.end_date.label('期末').asc(),).limit(4)
    
    df0=finance.run_query(q0).set_index('期末')

    dfs=pd.concat([df1,df0],axis=0)        
    dfs.index.name = '财报期'
    #dfs = dfs.style.highlight_max(color='yellow') 
    
    return dfs


# In[4]:


def show_profit(dfs,code):
    '''
    根据输入的的df返回净利润及同比走势图
    '''
    fig, ax1 = plt.subplots(dpi=70,facecolor='w')
    ax2 = ax1.twinx()
    dfs.plot.bar(ax=ax2,y=['净利润'],figsize=(14,5),rot=0,width=0.25,title=get_security_info(code).display_name+'-利润图')
    dfs.plot(ax=ax1,y=['同比%'],color=['darkorange'])

    ax1.legend(loc='lower left')
    ax2.legend(loc='lower right')
    plt.grid(linestyle=':',axis='y',which='major')
    
    return plt.show()


# In[5]:


#耗时较长
def show_inds(df,indus):
    
    code=list(df['股票代码'])
    inds_list=[]
    for i in code:
        try:
            inds=get_industry(i)[i][indus]['industry_name']
        except:
            inds='未分类'
        inds_list.append(inds)
    df[indus]=inds_list
    return df


# In[6]:


def show_chart(code):

    porit = get_profit(code,end_date)

    show_profit(porit,code)


# In[7]:


get_ipython().run_cell_magic('time', '', "\nend_date = '2023-6-30'#业绩预告\n\nfa =show_inds(forcast(end_date),'sw_l3')")


# In[8]:


# 获取每个下拉框的选项
publish_dates = fa['发布日期'].unique()
report_end_dates = fa['报告截止'].unique()
report_periods = fa['报告期'].unique()
forecast_types = fa['预告类型'].unique()
sw_l3_values = fa['sw_l3'].unique()

# 创建下拉框组件
publish_date_dropdown = widgets.SelectMultiple(
    options=['全选'] + list(publish_dates),
    value=[publish_dates[0]],  # 默认选择第一个值
    description='发布日期：'
)
report_end_date_dropdown = widgets.SelectMultiple(
    options=['全选'] + list(report_end_dates),
    value=['全选'],
    description='报告截止：'
)
report_period_dropdown = widgets.SelectMultiple(
    options=['全选'] + list(report_periods),
    value=['全选'],
    description='报告期：'
)
forecast_type_dropdown = widgets.SelectMultiple(
    options=['全选'] + list(forecast_types),
    value=['全选'],
    description='预告类型：'
)
sw_l3_dropdown = widgets.SelectMultiple(
    options=['全选'] + list(sw_l3_values),
    value=['全选'],
    description='行业分类：'
)

# 创建输出区域
output1 = widgets.Output(layout=widgets.Layout(height='auto', overflow='auto', max_height='800px', scrollable=True))
output2 = widgets.Output(layout=widgets.Layout(height='auto', overflow='auto', max_height='800px', scrollable=True))

# 创建画图按钮
button = widgets.Button(description='画图', layout=widgets.Layout(width='90px',height='50px'))
button.style.button_color = 'lightblue'


# 定义回调函数，用于根据选择的值更新显示结果
def update_display(*args):
    with output1:
        clear_output()  # 清除之前的结果
        
        selected_publish_dates = publish_date_dropdown.value
        selected_report_end_dates = report_end_date_dropdown.value
        selected_report_periods = report_period_dropdown.value
        selected_forecast_types = forecast_type_dropdown.value
        selected_sw_l3_values = sw_l3_dropdown.value
        
        if '全选' in selected_publish_dates:
            selected_publish_dates = list(publish_dates)
        
        if '全选' in selected_report_end_dates:
            selected_report_end_dates = list(report_end_dates)
        
        if '全选' in selected_report_periods:
            selected_report_periods = list(report_periods)
        
        if '全选' in selected_forecast_types:
            selected_forecast_types = list(forecast_types)
        
        if '全选' in selected_sw_l3_values:
            selected_sw_l3_values = list(sw_l3_values)
        
        filtered_df = fa[
            (fa['发布日期'].isin(selected_publish_dates)) &
            (fa['报告截止'].isin(selected_report_end_dates)) &
            (fa['报告期'].isin(selected_report_periods)) &
            (fa['预告类型'].isin(selected_forecast_types)) &
            (fa['sw_l3'].isin(selected_sw_l3_values))
        ]

        if filtered_df.empty:
            print("没有匹配的结果")
        else:
            display(filtered_df)

        return filtered_df['股票代码'].tolist()

# 创建回调函数，用于画图按钮点击事件
def on_button_clicked(button):
    with output2:
        clear_output()  # 清除之前的绘图结果
        selected_stock_codes = []
        stock_codes = update_display()
        for stock_code in stock_codes:
            show_chart(stock_code)  # 调用show_chart()函数画图

# 绑定回调函数到下拉框的value属性
publish_date_dropdown.observe(update_display, 'value')
report_end_date_dropdown.observe(update_display, 'value')
report_period_dropdown.observe(update_display, 'value')
forecast_type_dropdown.observe(update_display, 'value')
sw_l3_dropdown.observe(update_display, 'value')

# 绑定回调函数到画图按钮的on_click事件
button.on_click(on_button_clicked)

# 创建水平布局容器，并显示下拉框、画图按钮和输出结果
inputs = widgets.HBox([publish_date_dropdown, report_end_date_dropdown, report_period_dropdown, forecast_type_dropdown, sw_l3_dropdown, button])
display(inputs, output1, output2)

# 显示初始结果
update_display()
print('end')


# In[ ]:





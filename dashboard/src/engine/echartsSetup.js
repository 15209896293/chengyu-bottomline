/**
 * echartsSetup.js — ECharts 按需引入
 *
 * 全量 echarts 约 1MB（gzip 343KB）；按需注册仅用到的图表与组件，
 * 显著降低首屏 JS 体积。项目仅使用 line/bar/radar 三类图表。
 */
import * as echarts from 'echarts/core'
import { LineChart, BarChart, RadarChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  LineChart,
  BarChart,
  RadarChart,
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  CanvasRenderer,
])

export default echarts

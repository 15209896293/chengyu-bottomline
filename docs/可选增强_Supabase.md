# Supabase 可选增强 — 场景保存 / 用户系统

> 状态：**可选增强，不阻塞当前交付**。核心系统已完全离线可用（本地 JSON 数据层），
> Supabase 只服务"线上演示版的协作/个性化"，按需启用。

## 架构定位（决策记录）

```
┌─ 算法层 ──────────  Python 管线 step1-23（离线可复现）
├─ 推演层 ──────────  前端 realTimeEngine.js（浏览器实时计算，无后端依赖）
└─ 数据层 ──────────  离线：本地 JSON（dashboard/public/data/）
                     线上：Supabase（可选）——场景保存/用户系统/成果收藏
```

Supabase 是 **BaaS（Postgres + Auth + REST + Realtime）**，Edge Functions 是 JS 运行时，
**跑不了 geopandas/networkx 重计算**——因此它注定是数据层，不是计算引擎。核心算法
留在 Python（离线）与前端引擎（实时），线上只是加了一层"协作存储"。

## 为什么当前不加

1. **核心价值已闭环**：压测→逆压测→VaR→动态传染→预算优化全链路已离线可演示；
2. **演示风险**：国赛线下答辩，依赖 Supabase 在线服务有断网/配额风险；
3. **合规确认**：大赛无禁止云端依赖条款（官方调研结论），但"部署包或可访问链接"
   二选一提交时，离线包更稳。

## 若未来启用（接线步骤）

1. 创建 Supabase 项目（supabase.com），复制 URL + anon key
2. 建表：
   ```sql
   create table saved_scenarios (
     id uuid primary key default gen_random_uuid(),
     user_id uuid references auth.users,
     name text,
     params jsonb,          -- 震级/破裂位置/依赖权重等推演参数
     result jsonb,          -- 推演结果快照（KPI/系统状态）
     created_at timestamptz default now()
   );
   ```
3. 前端：`@supabase/supabase-js` 客户端，场景保存/加载按钮
4. 部署：Cloudflare Pages 环境变量注入 Supabase URL/anon key
5. 注意：**核心推演仍走前端引擎**，Supabase 只存参数与结果快照，不承载计算

## 数据合规提醒（参赛总则第 4 条）

上云的数据集需脱敏、来源合规：本项目数据均为公开来源（OSM/高德 POI/统计年鉴/
CAFD 断层数据库），不涉及个人隐私数据；若后续接入用户系统，用户信息需匿名化。

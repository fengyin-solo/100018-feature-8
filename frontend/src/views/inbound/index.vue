<template>
  <section class="page" data-module="inbound">
    <header class="page-head">
      <div>
        <h2>入库管理管理</h2>
        <p class="page-desc">维护入库单，围绕入库单号、供应商名称、货物名称、批次号做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记入库单</button>
        <button class="btn" type="button" @click="exportRows">导出入库管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              :disabled="acting"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!availableActions(row).length" class="action-hint">流程已终结</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无入库管理数据，可先登记入库单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条入库管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/inbound'
const columns = ["入库单号", "供应商名称", "货物名称", "批次号", "入库数量", "到货温度", "收货人", "入库时间"]
// 与后端流转口径保持一致：只有列出的状态才放行对应动作，其余状态不给入口。
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  待收货: ["确认收货", "退回入库"],
  已收货: ["安排上架", "退回入库"],
  已上架: [],
  已退回: [],
}
const stats = [{"label": "今日入库单", "value": 0}, {"label": "待上架单", "value": 0}, {"label": "到货温度不达标", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const acting = ref(false)
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function availableActions(row: Row): string[] {
  return ACTIONS_BY_STATUS[String(row.status ?? '')] ?? []
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '入库单登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  if (acting.value) {
    return
  }
  errorMessage.value = ''
  const values: Record<string, string> = { action }
  if (action === '确认收货') {
    const input = window.prompt(`录入入库单 ${row['入库单号'] ?? row.id} 的到货温度（℃）`)
    if (input === null) {
      return
    }
    if (!input.trim()) {
      errorMessage.value = '确认收货前请先录入到货温度（摄氏度数值，例如 -18）'
      return
    }
    values['到货温度'] = input.trim()
  }
  acting.value = true
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify(values),
    })
    const payload = await response.json().catch(() => null) as { ok?: boolean; message?: string } | null
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '入库管理动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '入库管理操作失败'
  } finally {
    acting.value = false
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('入库单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '入库管理列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.action-hint {
  color: var(--muted);
  font-size: 12px;
}

.link:disabled {
  color: var(--muted);
  cursor: not-allowed;
}
</style>

<script setup>
/**
 * Tag — 通用状态标签
 * 5种变体：normal / warning / collapse / pressure / info
 */
const props = defineProps({
  variant: { type: String, default: 'normal' },
  size: { type: String, default: 'md' }
})

const variantClass = {
  normal:   'tag-normal',
  warning:  'tag-warning',
  collapse: 'tag-collapse',
  pressure: 'tag-pressure',
  info:     'tag-info'
}

const sizeClass = {
  sm: 'tag-sm',
  md: 'tag-md'
}
</script>

<template>
  <span
    class="tag"
    :class="[variantClass[props.variant], sizeClass[props.size]]"
  >
    <span v-if="$slots.icon" class="tag-icon"><slot name="icon" /></span>
    <slot />
  </span>
</template>

<style scoped>
.tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-weight: 600;
  border-radius: var(--radius-sm);
  white-space: nowrap;
  line-height: 1;
}

.tag-md {
  font-size: var(--text-micro);
  padding: 3px 8px;
}

.tag-sm {
  font-size: 9px;
  padding: 2px 6px;
}

.tag-icon {
  display: inline-flex;
  align-items: center;
}

/* normal — 正常/达标 */
.tag-normal {
  background: var(--success-dim);
  color: var(--success);
}

/* warning — 警告/退化 */
.tag-warning {
  background: var(--warning-dim);
  color: var(--warning);
}

/* collapse — 崩溃/危险 */
.tag-collapse {
  background: var(--error-dim);
  color: var(--error);
}

/* pressure — 承压/预警 */
.tag-pressure {
  background: var(--orange-dim);
  color: var(--orange);
}

/* info — 信息/主色 */
.tag-info {
  background: var(--primary-dim);
  color: var(--primary);
}
</style>

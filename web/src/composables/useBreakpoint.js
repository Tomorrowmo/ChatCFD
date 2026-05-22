// Reactive viewport breakpoint detection.
// Tracks viewport width (not user-agent) so the same code adapts to phones,
// tablets and resized desktop windows alike.
import { ref, onMounted, onUnmounted } from 'vue'

const MOBILE_QUERY = '(max-width: 768px)'

function matches() {
  return typeof window !== 'undefined' && window.matchMedia(MOBILE_QUERY).matches
}

export function useBreakpoint() {
  const isMobile = ref(matches())
  let mql = null

  function update(e) {
    isMobile.value = e.matches
  }

  onMounted(() => {
    mql = window.matchMedia(MOBILE_QUERY)
    isMobile.value = mql.matches
    mql.addEventListener('change', update)
  })

  onUnmounted(() => {
    if (mql) mql.removeEventListener('change', update)
  })

  return { isMobile }
}

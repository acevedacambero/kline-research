import { describe, expect, it, vi } from 'vitest'
import { api } from './api'

describe('API errors', () => {
  it('surfaces the backend detail message instead of a generic status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      status: 503,
      json: async () => ({ detail: { code: 'AKSHARE_FETCH_FAILED', message: '行情获取失败：上游断开' } }),
    })))
    await expect(api.bars('sh', '601100')).rejects.toThrow('行情获取失败：上游断开')
  })
})

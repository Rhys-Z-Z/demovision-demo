import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// base64 编码文件绝对路径（兼容中文/空格，与后端 base64.b64decode 对应）
export function encodeFilePath(absPath) {
  return btoa(unescape(encodeURIComponent(absPath)))
}

// 拼接安全下载地址
export function downloadUrl(absPath) {
  return `/api/files/download?path=${encodeFilePath(absPath)}`
}

export function openDownload(absPath) {
  if (!absPath) return
  window.open(downloadUrl(absPath), '_blank')
}

// 从 Content-Disposition 解析文件名（兼容中文 RFC5987）
function filenameFromDisposition(disposition) {
  if (!disposition) return null
  const utf8 = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1].replace(/["']/g, ''))
    } catch (e) {
      /* fallthrough */
    }
  }
  const plain = disposition.match(/filename="?([^";]+)"?/i)
  return plain ? plain[1].trim() : null
}

// 统一下载收口（F4）：axios blob + Content-Disposition 文件名
export async function downloadBlob(url, fallbackName) {
  const resp = await api.get(url, { responseType: 'blob' })
  const disposition = resp.headers['content-disposition']
  let name = filenameFromDisposition(disposition) || fallbackName
  if (!name) {
    // 兜底：从 url 提取
    const parts = url.split('/')
    name = parts[parts.length - 1] || 'download'
  }
  const blobUrl = window.URL.createObjectURL(new Blob([resp.data]))
  const a = document.createElement('a')
  a.href = blobUrl
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(blobUrl)
}

export default api

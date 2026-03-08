export interface ErrorBody {
  code: string
  message: string
  category: string
  hint?: string
  context?: Record<string, unknown>
  request_id?: string
}

export class ApiError extends Error {
  code: string
  category: string
  hint?: string
  context?: Record<string, unknown>
  requestId?: string

  constructor(error: ErrorBody) {
    super(error.message)
    this.name = 'ApiError'
    this.code = error.code
    this.category = error.category
    this.hint = error.hint
    this.context = error.context
    this.requestId = error.request_id
  }
}

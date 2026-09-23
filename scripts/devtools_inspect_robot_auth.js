/**
 * Opentrons App/ODD: inspect CRS login token(s) from DevTools.
 *
 * Best: DevTools -> Sources -> Snippets -> New snippet -> paste -> Cmd/Ctrl+Enter
 * Or paste the one-liner at the bottom of this file into Console.
 *
 * Needs Developer Tools enabled so `window.store` exists.
 */
function inspectRobotAuth(opts = {}) {
  const store = window.store
  if (!store?.getState) {
    throw new Error(
      'window.store missing: enable Developer Tools and relaunch'
    )
  }
  const { perRobotAuthStates, mostRecentRobotName } = store.getState().robotAuth
  const rows = Object.entries(perRobotAuthStates || {})
    .filter(([, a]) => a)
    .filter(([name]) => !opts.robotName || name === opts.robotName)
    .map(([robot, a]) => ({
      robot,
      username: a.user?.username,
      accountType: a.user?.accountType,
      accessToken: opts.redact
        ? `${a.accessToken?.slice(0, 6)}…${a.accessToken?.slice(-4)}`
        : a.accessToken,
      refreshToken: opts.redact
        ? a.refreshToken &&
          `${a.refreshToken.slice(0, 6)}…${a.refreshToken.slice(-4)}`
        : a.refreshToken,
      expiresAt: a.expiresAt ? new Date(a.expiresAt).toISOString() : null,
      secondsLeft: a.expiresAt
        ? Math.round((a.expiresAt - Date.now()) / 1000)
        : null,
    }))
  if (!rows.length) console.warn('Not logged in to any robot')
  else console.table(rows)
  return { mostRecentRobotName, rows }
}

function copyAccessToken(robotName) {
  const { perRobotAuthStates, mostRecentRobotName } = store.getState().robotAuth
  const name = robotName || mostRecentRobotName
  const token = perRobotAuthStates?.[name]?.accessToken
  if (!token) throw new Error(`No accessToken for ${name}`)
  return navigator.clipboard.writeText(token).then(() => {
    console.log(`Copied accessToken for ${name}`)
    return token
  })
}

inspectRobotAuth()

/*
 * Console one-liner (if you cannot use Snippets):
 *
 * store.getState().robotAuth
 *
 * Or table view:
 *
 * console.table(Object.entries(store.getState().robotAuth.perRobotAuthStates).filter(([,a])=>a).map(([robot,a])=>({robot,...a.user,accessToken:a.accessToken,refreshToken:a.refreshToken,expiresAt:a.expiresAt&&new Date(a.expiresAt).toISOString()})))
 */

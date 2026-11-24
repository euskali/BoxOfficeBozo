export default function ErrorBox({ error }: { error: Error }) {
  return (
    <div className="box mb-3" role="alert">
      <div className="bar text-body">Error!</div>
      <div className="p-2">
        <p>
          Something went wrong loading the data: <code>{error.message}</code>
        </p>
        <button type="button" className="btn-bevel" onClick={() => window.location.reload()}>
          [ Try again ]
        </button>
      </div>
    </div>
  )
}

export function WorkspaceSkeleton() {
  return (
    <div className="flex flex-col h-screen">
      {/* Navbar skeleton */}
      <div className="navbar bg-base-100 border-b border-base-300 px-4">
        <div className="flex-1">
          <div className="skeleton h-8 w-32" />
        </div>
        <div className="flex-none">
          <div className="skeleton h-8 w-8 rounded-full" />
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Left panel skeleton */}
        <div className="w-[400px] shrink-0 border-r border-base-300 p-4 flex flex-col gap-4">
          {/* AudioPlayer placeholder */}
          <div className="skeleton h-20 w-full" />
          <div className="skeleton h-3 w-full" />
          <div className="skeleton h-8 w-full" />

          <div className="divider my-0" />

          {/* SummaryPanel placeholder */}
          <div className="skeleton h-4 w-24" />
          <div className="skeleton h-3 w-full" />
          <div className="skeleton h-3 w-full" />
          <div className="skeleton h-3 w-3/4" />

          <div className="divider my-0" />

          {/* CompliancePanel placeholder */}
          <div className="skeleton h-4 w-24" />
          <div className="skeleton h-16 w-full" />
        </div>

        {/* Right panel skeleton */}
        <div className="flex-1 p-4 flex flex-col gap-3">
          {/* Toolbar placeholder */}
          <div className="skeleton h-10 w-full rounded-lg" />

          {/* Chat bubbles placeholder */}
          <div className="flex flex-col gap-4 mt-2">
            <div className="flex gap-3">
              <div className="skeleton h-10 w-10 rounded-full shrink-0" />
              <div className="skeleton h-16 w-2/3 rounded-2xl" />
            </div>
            <div className="flex gap-3 justify-end">
              <div className="skeleton h-20 w-2/3 rounded-2xl" />
              <div className="skeleton h-10 w-10 rounded-full shrink-0" />
            </div>
            <div className="flex gap-3">
              <div className="skeleton h-10 w-10 rounded-full shrink-0" />
              <div className="skeleton h-12 w-1/2 rounded-2xl" />
            </div>
            <div className="flex gap-3 justify-end">
              <div className="skeleton h-16 w-3/5 rounded-2xl" />
              <div className="skeleton h-10 w-10 rounded-full shrink-0" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

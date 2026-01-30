"""
Batch Processor v79.0
Progress bar and parallel processing for recalculation.
"""
import sys
import time
from dataclasses import dataclass
from typing import Callable, Iterator, TypeVar, Generic
from concurrent.futures import ThreadPoolExecutor, as_completed

T = TypeVar('T')
R = TypeVar('R')


@dataclass
class BatchResult:
    """Result of batch processing."""
    processed: int
    changed: int
    errors: int
    elapsed_seconds: float

    @property
    def rate(self) -> float:
        """Items per second."""
        if self.elapsed_seconds > 0:
            return self.processed / self.elapsed_seconds
        return 0.0


class ProgressBar:
    """Simple progress bar for terminal."""

    def __init__(self, total: int, prefix: str = '', width: int = 40):
        self.total = total
        self.prefix = prefix
        self.width = width
        self.current = 0
        self.changed = 0
        self.start_time = time.time()

    def update(self, current: int = None, changed: int = None):
        """Update progress bar."""
        if current is not None:
            self.current = current
        else:
            self.current += 1

        if changed is not None:
            self.changed = changed

        self._render()

    def increment(self, was_changed: bool = False):
        """Increment by 1."""
        self.current += 1
        if was_changed:
            self.changed += 1
        self._render()

    def _render(self):
        """Render progress bar to terminal."""
        if self.total == 0:
            return

        percent = self.current / self.total
        filled = int(self.width * percent)
        # Use ASCII-safe characters for Windows cp1251 compatibility
        bar = '#' * filled + '-' * (self.width - filled)

        elapsed = time.time() - self.start_time
        rate = self.current / elapsed if elapsed > 0 else 0
        eta = (self.total - self.current) / rate if rate > 0 else 0

        status = f"{self.current}/{self.total} ({self.changed} changed)"
        timing = f"{rate:.1f}/s, ETA {eta:.0f}s"

        line = f"\r{self.prefix} [{bar}] {percent:6.1%} {status} | {timing}"
        sys.stdout.write(line)
        sys.stdout.flush()

    def finish(self):
        """Finish progress bar."""
        elapsed = time.time() - self.start_time
        print(f"\nDone: {self.current} processed, {self.changed} changed in {elapsed:.1f}s")


class BatchProcessor(Generic[T, R]):
    """
    Generic batch processor with progress tracking.

    Usage:
        processor = BatchProcessor(
            items=channels,
            process_fn=recalculate_channel,
            batch_size=100
        )
        result = processor.run()
    """

    def __init__(
        self,
        items: list[T],
        process_fn: Callable[[T], R],
        batch_size: int = 100,
        show_progress: bool = True,
        parallel: bool = False,
        max_workers: int = 4,
    ):
        self.items = items
        self.process_fn = process_fn
        self.batch_size = batch_size
        self.show_progress = show_progress
        self.parallel = parallel
        self.max_workers = max_workers

    def run(self) -> tuple[list[R], BatchResult]:
        """
        Run batch processing.

        Returns:
            Tuple of (results list, BatchResult stats)
        """
        start_time = time.time()
        results = []
        changed = 0
        errors = 0

        total = len(self.items)
        progress = None

        if self.show_progress:
            progress = ProgressBar(total, prefix='Processing')

        if self.parallel and self.max_workers > 1:
            results, changed, errors = self._run_parallel(progress)
        else:
            results, changed, errors = self._run_sequential(progress)

        if progress:
            progress.finish()

        elapsed = time.time() - start_time

        return results, BatchResult(
            processed=len(results),
            changed=changed,
            errors=errors,
            elapsed_seconds=elapsed
        )

    def _run_sequential(self, progress: ProgressBar = None) -> tuple[list[R], int, int]:
        """Sequential processing."""
        results = []
        changed = 0
        errors = 0

        for item in self.items:
            was_changed = False
            try:
                result = self.process_fn(item)
                results.append(result)

                # Check if result indicates a change
                if hasattr(result, 'changed') and result.changed:
                    changed += 1
                    was_changed = True
                elif isinstance(result, tuple) and len(result) > 1 and result[1]:
                    changed += 1
                    was_changed = True

            except Exception as e:
                errors += 1
                results.append(None)

            if progress:
                progress.increment(was_changed=was_changed)

        return results, changed, errors

    def _run_parallel(self, progress: ProgressBar = None) -> tuple[list[R], int, int]:
        """Parallel processing using ThreadPoolExecutor."""
        results = [None] * len(self.items)
        changed = 0
        errors = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_idx = {
                executor.submit(self.process_fn, item): idx
                for idx, item in enumerate(self.items)
            }

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    result = future.result()
                    results[idx] = result

                    if hasattr(result, 'changed') and result.changed:
                        changed += 1

                except Exception as e:
                    errors += 1
                    results[idx] = None

                if progress:
                    progress.increment()

        return results, changed, errors


def chunked(items: list[T], size: int) -> Iterator[list[T]]:
    """Split list into chunks of given size."""
    for i in range(0, len(items), size):
        yield items[i:i + size]

"""Project-specific exceptions."""


class CottonFactorError(Exception):
    """Base exception for cotton-factor failures."""


class IngestError(CottonFactorError):
    """Base exception for raw ingestion failures."""


class FetchError(IngestError):
    """Raised when a raw source cannot be fetched."""


class ConfigError(CottonFactorError):
    """Raised when repository configuration is invalid."""


class ContractMasterError(CottonFactorError):
    """Raised when contract master generation cannot proceed."""


class TradingCalendarError(CottonFactorError):
    """Raised when trading calendar loading or navigation fails."""


class CoreNormalizationError(CottonFactorError):
    """Raised when raw snapshots cannot be normalized into core facts."""


class ChainMapError(CottonFactorError):
    """Raised when continuous chain mapping cannot be built."""


class TradeMappingError(CottonFactorError):
    """Raised when signal-to-trade mapping cannot be built."""


class ContinuousPriceError(CottonFactorError):
    """Raised when continuous price generation cannot proceed."""


class FactorError(CottonFactorError):
    """Raised when factor framework validation or computation cannot proceed."""


class FactorRegistryError(FactorError):
    """Raised when factor registry config is invalid."""


class FactorDependencyError(FactorError):
    """Raised when a factor run is missing required normalized inputs."""


class ForwardReturnError(FactorError):
    """Raised when forward return construction cannot proceed."""


class FactorEvaluationError(FactorError):
    """Raised when single factor evaluation cannot proceed."""


class ReportRenderError(CottonFactorError):
    """Raised when an archive report cannot be rendered."""


class BacktestError(CottonFactorError):
    """Raised when daily backtest construction cannot proceed."""


class ArchiveError(CottonFactorError):
    """Raised when archive or audit artifact construction cannot proceed."""


class SmokeError(CottonFactorError):
    """Raised when an end-to-end smoke workflow cannot complete."""


class QAError(CottonFactorError):
    """Raised when QA validation or audit checks cannot complete."""


class UATError(CottonFactorError):
    """Raised when a UAT replay scenario cannot be prepared."""


class ReleaseError(CottonFactorError):
    """Raised when a release freeze package cannot be prepared."""


class RawSnapshotError(CottonFactorError):
    """Base exception for raw snapshot storage failures."""


class RawSnapshotExistsError(RawSnapshotError):
    """Raised when a snapshot id already exists in the raw manifest."""


class RawSnapshotIntegrityError(RawSnapshotError):
    """Raised when a stored raw snapshot fails replay integrity checks."""


class RawSnapshotNotFoundError(RawSnapshotError):
    """Raised when a requested raw snapshot id is not present in the manifest."""

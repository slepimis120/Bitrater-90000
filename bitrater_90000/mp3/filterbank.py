import numpy as np

from bitrater_90000.mp3.tables import ENWINDOW

GRANULE = 576
SUBBANDS = 32
SUBBAND_SAMPLES = 18


def _analysis_window() -> np.ndarray:
    d = np.zeros(512)
    for i, value in enumerate(ENWINDOW):
        v = value / 65536
        d[i] = v
        if i % 64:
            v = -v
        if i:
            d[512 - i] = v
    return d / 32


_WINDOW = _analysis_window()

_MATRIX = np.cos(
    (2 * np.arange(SUBBANDS)[:, None] + 1) * (np.arange(64)[None, :] - 16) * np.pi / 64
)

_n = np.arange(2 * SUBBAND_SAMPLES)
_k = np.arange(SUBBAND_SAMPLES)
_MDCT = np.cos(np.pi / 72 * (2 * _n[None, :] + 1 + 18) * (2 * _k[:, None] + 1)) / 9
_WINDOW_LONG = np.sin(np.pi / 36 * (_n + 0.5))

_C = np.array([-0.6, -0.535, -0.33, -0.185, -0.095, -0.041, -0.0142, -0.0037])
_CS = 1 / np.sqrt(1 + _C ** 2)
_CA = _C / np.sqrt(1 + _C ** 2)


def polyphase_analysis(x: np.ndarray) -> np.ndarray:
    n_blocks = (len(x) - 512) // SUBBANDS
    idx = SUBBANDS * np.arange(n_blocks)[:, None] + 511 - np.arange(512)[None, :]
    z = x[idx] * _WINDOW
    y = z.reshape(n_blocks, 8, 64).sum(axis=1)
    return y @ _MATRIX.T


def analyze(x: np.ndarray, offset: int) -> np.ndarray:
    if offset < 0:
        x = np.concatenate([np.zeros(-offset), x])
    else:
        x = x[offset:]

    s = polyphase_analysis(x)
    n_granules = len(s) // SUBBAND_SAMPLES
    s = s[: n_granules * SUBBAND_SAMPLES].reshape(n_granules, SUBBAND_SAMPLES, SUBBANDS)

    s[:, 1::2, 1::2] *= -1

    previous = np.concatenate([np.zeros((1, SUBBAND_SAMPLES, SUBBANDS)), s[:-1]])
    blocks = np.concatenate([previous, s], axis=1) * _WINDOW_LONG[None, :, None]
    coef = np.einsum("kn,gns->gsk", _MDCT, blocks)

    for i in range(8):
        upper = coef[:, :-1, 17 - i].copy()
        lower = coef[:, 1:, i].copy()
        coef[:, :-1, 17 - i] = upper * _CS[i] + lower * _CA[i]
        coef[:, 1:, i] = lower * _CS[i] - upper * _CA[i]

    return coef.reshape(n_granules, GRANULE)
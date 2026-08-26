"""
Application entry point for the AI analyst backend.

This module instantiates the FastAPI app and includes all API
routers. It also provides a root path description for the API.
"""

import logging
import time
import uuid as _uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .api import router as api_router
from .startup import print_startup_diagnostics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """FastAPI lifespan handler: startup diagnostics + DB init, then DB shutdown."""
    print_startup_diagnostics()

    # Phase 9A â€” initialise persistence layer (no-op when DATABASE_URL is empty)
    try:
        from .config import settings as _settings
        from .db import init_db
        await init_db(_settings.database_url)
    except Exception as _exc:
        logger.warning("[startup] persistence layer init failed (non-fatal): %r", _exc)

    # Phase 9F â€” seed historical analogs (idempotent; skips rows that already exist)
    try:
        from .db import get_session as _get_session
        from .db.repositories.evidence_repo import seed_analogs as _seed_analogs
        async with _get_session() as _seed_session:
            if _seed_session is not None:
                _inserted = await _seed_analogs(_seed_session)
                logger.info("[startup] 9F analog seed: %d rows inserted", _inserted)
    except Exception as _seed_exc:
        logger.warning("[startup] 9F analog seed failed (non-fatal): %r", _seed_exc)

    # Phase 10C delivery_ledger column additions have moved OUT of startup into a
    # versioned, reversible Alembic migration (0002_delivery_ledger_severity).
    # Startup no longer issues DDL; run `alembic upzÓm¢G§²ÚîÆ­yÒÂ&W‡"Â&VB"Â&—72%×ÒÀ¢¢&WGW&â–Æö@¢W†6WBW†6WF–öâ2W†3 ¢ÆövvW"æFV'Vr‚%¶WF…Ò7–ÖÖWG&–2¥uBfW&–f–6F–öâf–ÆVC¢W""ÂW†2¢&WGW&âæöæP  ¦7–æ2FVb÷fW&–g•÷Fö¶Vâ‡Fö¶Vã¢7G"’Óâ÷F–öæÅ´F–7EÓ ¢""%W6RÆVv7’…3#Sbv†Vâ6öæf–wW&VBÂ÷F†W'v—6R7W&6R¥tµ2fW&–f–6F–öâà ¢&WGW&ç2F†RfW&–f–VB–ÆöBF–7B÷"æöæRà¢"" ¢g&öÒæ6öæf–r–×÷'B6WGF–æw22÷6WGF–æw0 ¢2…3#SbFƒ¢&VfW"v†Vâ¥uB6V7&WB—26öæf–wW&V@¢–b÷6WGF–æw2ç7W&6Uö§wE÷6V7&WC ¢&WGW&â÷fW&–g•ö§wEö‡3#Sb€¢Fö¶VâÀ¢÷6WGF–æw2ç7W&6Uö§wE÷6V7&WBÀ¢÷6WGF–æw2ç7W&6UöVF–Væ6RÀ¢ ¢27W'&VçB7W&6R&ö¦V7G2W6Râ7–ÖÖWG&–26–væ–ær¶W’†æ÷&ÖÆÇ’U3#Sb’à¢–b÷6WGF–æw2ç7W&6U÷&ö¦V7E÷W&Ã ¢&WGW&âv—B÷fW&–g•ö§wEö7–ÖÖWG&–2€¢Fö¶VâÀ¢÷6WGF–æw2ç7W&6U÷&ö¦V7E÷W&ÂÀ¢÷6WGF–æw2ç7W&6UöVF–Væ6RÀ¢ ¢ÆövvW"çv&æ–ær€¢%¶WF…ÒUD…ôTä$ÄTC×G'VR'WBæV—F†W"7W&6Uö§wE÷6V7&WBæ÷" ¢'7W&6U÷&ö¦V7E÷W&Â—26öæf–wW&VB(	BÆÂ&WVW7G2VæWF†VçF–6FVB ¢¢&WGW&âæöæP  ¦7–æ2FVb÷&W6öÇfUö–FVçF—G’‡&WVW7C¢&WVW7B’ÓâGWÆU´÷F–öæÅ·7G%ÒÂ÷F–öæÅ·7G%ÒÂ&ööÅÓ ¢""%&WGW&â‡W6W%ö–BÂWF…÷7V&¦V7BÂ—5öWF†VçF–6FVB’f÷"F†R&WVW7Bà ¢'—72ÖöFR„UD…ôTä$ÄTCÖfÇ6R“ ¢(i"…5•5DTÕôDTdTÅEõU4U%ô”BÂæöæRÂfÇ6R’Çv—2(	BæòFö¶Vâ–ç7V7F–öâà ¢Væf÷&6VÖVçBÖöFR„UD…ôTä$ÄTC×G'VR“ ¢fÆ–B¥uB(i"‡7V"Â7V"ÂG'VR¢æòFö¶Vâ(i"„æöæRÂæöæRÂfÇ6R¢&BFö¶Vâ(i"„æöæRÂæöæRÂfÇ6R¢"" ¢g&öÒæ6öæf–r–×÷'B6WGF–æw22÷6WGF–æw0 ¢–bæ÷B÷6WGF–æw2æWF…öVæ&ÆVC ¢&WGW&â÷6WGF–æw2æWF…ö'—75÷W6W%ö–BÂæöæRÂfÇ6P ¢2Væf÷&6VÖVçBF‚(	BöæÇ’&V6†VBv†VâUD…ôTä$ÄTC×G'VP¢Fö¶VâÒöW‡G&7Eö&V&W%÷Fö¶Vâ‡&WVW7B¢–bFö¶Vâ—2æöæS ¢&WGW&âæöæRÂæöæRÂfÇ6P ¢–ÆöBÒv—B÷fW&–g•÷Fö¶Vâ‡Fö¶Vâ¢–b–ÆöB—2æöæS ¢&WGW&âæöæRÂæöæRÂfÇ6P ¢7V"Ò–ÆöBævWB‚'7V""¢–bæ÷B7V# ¢&WGW&âæöæRÂæöæRÂfÇ6P ¢2&W6W'fRöæÇ’F†RfW&–f–VB6Æ–×2f÷"f—'7BÖÆöv–â&÷f—6–öæ–ærâF†—2—0¢2–çFW&æÂ&WVW7B7FFRæB—2æWfW"&WGW&æVBF—&V7FÇ’Fò6Æ–VçG2à¢&WVW7Bç7FFRæWF…ö6Æ–×2Ò–Æö@¢&WGW&â7V"Â7V"ÂG'VP  ¦7–æ2FVb÷&W6öÇfUöÆö6Å÷W6W%ö–B‡&WVW7C¢&WVW7B’Óâ÷F–öæÅ·7G%Ó ¢""%&÷f—6–öâ÷"&W6öÇfRF†RÆö6Â÷væW"f÷"fW&–f–VB¥uB6Æ–×2à ¢F†RÆö6Â”B6âF–ffW"g&öÒF†R7W&6R7V&¦V7Bv†VââöÆFW"Æö6À¢66÷VçB—2Æ–æ¶VB'’VÖ–Ââ&÷FV7FVB&÷WFW2×W7BF†W&Vf÷&RW6RF†RÆö6À¢”B&WGW&æVB†W&R&F†W"F†â77VÖ–ær7V"ÓÒW6W'2æ–Fà¢"" ¢6Æ–×2ÒvWFGG"‡&WVW7Bç7FFRÂ&WF…ö6Æ–×2"ÂæöæR¢–bæ÷B—6–ç7Fæ6R†6Æ–×2ÂF–7B“ ¢&WGW&âæöæP ¢g&öÒæF"æ6öææV7F–öâ–×÷'BvWE÷6W76–öà¢g&öÒç6W'f–6W2ç7W&6UöWF…÷6W'f–6R–×÷'B&W6öÇfU÷W6W%ög&öÕö§w@ ¢7–æ2v—F‚vWE÷6W76–öâ‚’26W76–öã ¢–b6W76–öâ—2æöæS ¢&WGW&âæöæP¢W6W"Òv—B&W6öÇfU÷W6W%ög&öÕö§wB‡6W76–öâÂ6Æ–×2¢–bW6W"—2æöæS ¢&WGW&âæöæP¢v—B6W76–öâæ6öÖÖ—B‚¢&WGW&â7G"‡W6W"æ–B  ¢2ÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒĞ¢2Ö–FFÆWv&R6Æ70¢2ÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒĞ ¦6Æ72WF„Ö–FFÆWv&R„&6T…EEÖ–FFÆWv&R“ ¢""%7F&ÆWGFRÖ–FFÆWv&RF†B7F×2W6W"–FVçF—G’öçFò&WVW7Bç7FFRà ¢æWfW"&—6W2â&W6öÇWF–öâf–ÇW&W2&WF–âF†R'—72–FVçF—G’öæÇ’v†–ÆP¢WF‚—2F—6&ÆVC²Væf÷&6VÖVçBÖöFRÇv—2f–Ç26Æ÷6VBà¢""  ¢7–æ2FVbF—7F6‚‡6VÆbÂ&WVW7C¢&WVW7BÂ6ÆÅöæW‡B’Óâ&W7öç6S ¢&WVW7Bç7FFRæWF…ö6Æ–×2ÒæöæP¢G'“ ¢W6W%ö–BÂWF…÷7V&¦V7BÂ—5öWF†VçF–6FVBÒv—B÷&W6öÇfUö–FVçF—G’‡&WVW7B¢–b—5öWF†VçF–6FVC ¢W6W%ö–BÒv—B÷&W6öÇfUöÆö6Å÷W6W%ö–B‡&WVW7B¢–bW6W%ö–B—2æöæS ¢WF…÷7V&¦V7BÒæöæP¢—5öWF†VçF–6FVBÒfÇ6P¢W†6WBW†6WF–öâ2W†3 ¢ÆövvW"çv&æ–ær‚%¶WF…Ò÷&W6öÇfUö–FVçF—G’&—6VB†æöâÖfFÂ“¢W""ÂW†2¢g&öÒæ6öæf–r–×÷'B6WGF–æw22÷0¢W6W%ö–BÒ÷2æWF…ö'—75÷W6W%ö–B–bæ÷B÷2æWF…öVæ&ÆVBVÇ6RæöæP¢WF…÷7V&¦V7BÒæöæP¢—5öWF†VçF–6FVBÒfÇ6P ¢&WVW7Bç7FFRçW6W%ö–BÒW6W%ö–@¢&WVW7Bç7FFRæWF…÷7V&¦V7BÒWF…÷7V&¦V7@¢&WVW7Bç7FFRæ—5öWF†VçF–6FVBÒ—5öWF†VçF–6FV@ ¢2–FVçF—G’Öv&RÆ–Ö—G2'Vâ†W&RÂgFW"¥uB&W6öÇWF–öâæB&Vf÷&R&÷WFP¢2v÷&²âF†R÷WFW"VFvRwV&B–æFWVæFVçFÇ’Æ–Ö—G2WfW'’•Â–æ6ÇVF–æp¢2VæWF†VçF–6FVB6ÆÆW'2âF†R6†&VB'—72–FVçF—G’—2FVÆ–&W&FVÇ¢2æ÷BG&VFVB2&VÂW6W"'V6¶WB–âÆö6ÂFWfVÆ÷ÖVçBà¢g&öÒæ6öæf–r–×÷'B6WGF–æw22÷0¢–b÷2ç&FUöÆ–Ö—EöVæ&ÆVC ¢g&öÒæFWVæFVæ6–W2æWF‚–×÷'B5•5DTÕôDTdTÅEõU4U%ô”@¢g&öÒç6V7W&—G’ç&FUöÆ–Ö—B–×÷'B€¢6Æ–VçEö—Â—5öW†V×BÂ—5öW‡Vç6—fRÂÆöuöFVæ–ÂÂ&FUöÆ–Ö—FW"À¢ ¢–bæ÷B—5öW†V×B‡&WVW7B“ ¢6†V6·2ÒµĞ¢–b—5öWF†VçF–6FVBæBW6W%ö–BæBW6W%ö–BÒ5•5DTÕôDTdTÅEõU4U%ô”C ¢6†V6·2æVæB‚€¢b'W6W#§·W6W%ö–GÒ"À¢÷2ç&FUöÆ–Ö—E÷W%÷W6W%÷W%öÖ–âÀ¢&vÆö&Å÷W6W""À¢’¢–b—5öW‡Vç6—fR‡&WVW7B“ ¢—Ò6Æ–VçEö—‡&WVW7BÂ÷2ç&FUöÆ–Ö—E÷G'W7FVE÷&÷‡•ö†÷2¢6†V6·2æVæB‚€¢b&W‡Vç6—fS¦—§¶—Ò"À¢÷2ç&FUöÆ–Ö—EöW‡Vç6—fU÷W%ö—÷W%öÖ–âÀ¢&W‡Vç6—fUö—"À¢’¢–b—5öWF†VçF–6FVBæBW6W%ö–BæBW6W%ö–BÒ5•5DTÕôDTdTÅEõU4U%ô”C ¢6†V6·2æVæB‚€¢b&W‡Vç6—fS§W6W#§·W6W%ö–GÒ"À¢÷2ç&FUöÆ–Ö—EöW‡Vç6—fU÷W%÷W6W%÷W%öÖ–âÀ¢&W‡Vç6—fU÷W6W""À¢’ ¢f÷"¶W’ÂÆ–Ö—BÂ66÷R–â6†V6·3 ¢ÆÆ÷vVBÂ&WG'•ögFW"Ò&FUöÆ–Ö—FW"æ6†V6²€¢¶W’ÂÆ–Ö—BÂ÷2ç&FUöÆ–Ö—E÷v–æF÷u÷0¢¢–bæ÷BÆÆ÷vVC ¢ÆöuöFVæ–Â€¢66÷S×66÷RÂ&WVW7C×&WVW7BÂ&WG'•ögFW#×&WG'•ögFW ¢¢&WGW&â¥4ôå&W7öç6R€¢7FGW5ö6öFSÓC#’À¢6öçFVçC×²&FWF–Â#¢%&FRÆ–Ö—BW†6VVFVBâÆV6R6Æ÷rF÷vââ'ÒÀ¢†VFW'3×²%&WG'’ÔgFW"#¢7G"‡&WG'•ögFW"—ÒÀ¢ ¢&WGW&âv—B6ÆÅöæW‡B‡&WVW7B
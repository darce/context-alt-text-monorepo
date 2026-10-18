<?php

declare(strict_types=1);

namespace AltContext\Media;

class XmpPersistenceFactory {
	public static function create_attachment_xmp_metrics_persistor( ?FaceMetricsSourceInterface $source = null ): AttachmentXmpMetricsPersistor {
		$face_metrics_source = $source ?? new ProxyFaceMetricsSource();

		return new AttachmentXmpMetricsPersistor(
			new ImageXmpWriter(
				$face_metrics_source,
				new XmpImageRegionPacketBuilder(),
				new JpegXmpInjector(),
				new PngXmpInjector()
			)
		);
	}
}

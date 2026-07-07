<?php

declare(strict_types=1);

class Offer
{
    public string $code = '';

    public int $price = 0;

    public ?int $oldPrice = null;

    public bool $available = false;

    public ?string $countryCode = null;
}
